"""POI 富化·去哪儿（qunar）评分 + 评论数——fill-empty-only 收割通道。

背景（2026-11-12 用户拍板）：pois 表 rating 缺口 ~7.6k 行（status='active'）；
用户实测选定去哪儿为评分单源（与携程评分平均偏差 0.02，SSR 零反爬）。
复用 app/jobs/enrich_qunar_duration.py 勘察结论：sight.qunar.com 列表
``/list?city={slug}&page=N`` 每页 10 条（ld+json ItemList 给 (名, 数字 id)），
详情页 ``sight.qunar.com/{id}`` 纯 httpx GET 可得。

单点验证（2026-11-12 实测，颐和园 4268080051）：任务给的
``"aria-label":"4.6 分（满分 5 分）"`` JSON 形态在本机抓到的 SSR HTML 里
不存在——实际是 HTML 属性形态 ``aria-label="4.7 分（满分 5 分）"``，且评分
数字与「条评论」数字之间隔着 ``<!-- -->`` 注释节点（``34,602<!-- --> 条评论``）。
按任务约定 dump 片段后调整：主解析改用详情页 ld+json 的
``"aggregateRating":{"@type":"AggregateRating","ratingValue":4.7,
"reviewCount":34602,...}``（首见即主条目，一次给 rating+count 两列），
aria-label/条评论两正则做兜底交叉源；颐和园 4.7/34,602、故宫 4.9/55,276、
天坛 4.8/7,877 三点实测一致。

选行/写库口径：
  * targets = status='active' AND rating IS NULL AND city ∈ QUNAR_CITY_SLUGS，
    按 app.services.source_tier.SOURCE_PRIORITY 优先序（unesco/5a/curated/
    博物馆打头）+ rating 非空降序 + id 稳定序。
  * 匹配闸：列表页 (id,name) 对与名称变体互含（变体 ⊆ 列表名或列表名 ⊆
    变体，各 ≥2 字）才取；变体生成逻辑 import app.jobs.enrich_baidu_map._variants
    （原名/剥前缀行政区/剥尾缀景区词/组合名分段），不复制不修改。
  * 列表翻页最多 3 页/城；找不到记 ops/qunar_rating_missed.txt
    （poi_id + 原因），确定性失败只试一次。
  * 写库 fill-empty-only：rating / rating_count 空才写，rating 闸 0-5、
    rating_count 闸 ≤1000 万，rating_source='qunar'（仅在写入 rating 时
    打标——来源列归属 rating 本身）；每行单独 commit。
  * 礼貌节奏：并发 2、请求间 sleep 0.5-1s；连续 3 个详情页异常即停批。

用法（ops 层，repo 根运行）：
    .venv/Scripts/python -I ops/enrich_qunar_rating.py [--limit 300] [--city 北京]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import re
import sys
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo 根，供 -I 直跑

import httpx
from sqlalchemy import case

from app.db import get_session_factory
from app.jobs.enrich_baidu_map import _variants
from app.jobs.enrich_qunar_duration import QUNAR_CITY_SLUGS, parse_list_page
from app.models import Poi
from app.services.source_tier import SOURCE_PRIORITY

logger = logging.getLogger("ops.qunar_rating")

_DEFAULT_LIMIT = 300
_PAGES_PER_CITY_CAP = 15  # 匹配闸：列表最多翻 15 页/城（2026-11-12 加深：3 页只有 30 景点/城，命中率 5%）
_CONCURRENCY = 2
_SLEEP_MIN, _SLEEP_MAX = 0.5, 1.0
_BREAKER_DETAIL_ERRORS = 3  # 连续 3 个详情页异常即停批
_RATING_MIN, _RATING_MAX = 0.0, 5.0
_COUNT_MAX = 10_000_000
_RETRYABLE_STATUS = (429, 500, 502, 503, 504)
_MAX_ATTEMPTS = 4
_SOURCE_PRIORITY = SOURCE_PRIORITY  # 铁律 canonical order 唯一定义点

_LIST_URL = "https://sight.qunar.com/list?city={slug}&page={page}"
_DETAIL_URL = "https://sight.qunar.com/{poi_id}"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    )
}

# --- 解析：详情页主评分 / 评论数 ----------------------------------------------

# 主解析：ld+json aggregateRating（首见即主条目，一次取 rating + count；
# 2026-11-12 实测颐和园 4.7/34602、故宫 4.9/55276、天坛 4.8/7877）。
_AGG_RATING_RE = re.compile(
    r'"aggregateRating":\s*\{"@type":"AggregateRating",'
    r'"ratingValue":\s*([\d.]+),\s*"reviewCount":\s*(\d+)'
)
# 兜底交叉源 1：HTML 属性形态 aria-label="4.7 分（满分 5 分）"
# （任务所述 JSON 形态 "aria-label":"4.6 分（满分 5 分）" 一并兼容，首见即主条目）。
_ARIA_RATING_RE = re.compile(r'"?aria-label"?[:=]\s*"([\d.]+) 分（满分 5 分）"')
# 兜底交叉源 2：评论数（数字与「条评论」之间允许 <!-- --> 注释节点，千分位逗号）。
_COMMENT_RE = re.compile(r"([\d,]+)(?:<!--\s*-->)?\s*条评论")


def parse_detail_rating(html: str) -> tuple[float | None, int | None]:
    """详情页 HTML → (rating, rating_count)，主条目取首见；解析不出 (None, None)。

    主源 ld+json aggregateRating；缺任一列时用 aria-label / 条评论兜底补位。
    """
    rating: float | None = None
    count: int | None = None
    m = _AGG_RATING_RE.search(html)
    if m:
        rating = float(m.group(1))
        count = int(m.group(2))
    if rating is None:
        ma = _ARIA_RATING_RE.search(html)
        if ma:
            rating = float(ma.group(1))
    if count is None:
        mc = _COMMENT_RE.search(html)
        if mc:
            count = int(mc.group(1).replace(",", ""))
    return rating, count


def gate(rating: float | None, count: int | None) -> tuple[float | None, int | None]:
    """写库闸：rating 0-5、count ≤1000 万，出闸置 None（调用方计 invalid）。"""
    if rating is not None and not (_RATING_MIN <= rating <= _RATING_MAX):
        rating = None
    if count is not None and not (0 <= count <= _COUNT_MAX):
        count = None
    return rating, count


# --- 目标行选取 ---------------------------------------------------------------


def _source_rank():
    whens = [(Poi.source == src, rank) for rank, src in enumerate(_SOURCE_PRIORITY)]
    return case(*whens, else_=len(_SOURCE_PRIORITY))


def select_targets(
    session_factory, *, limit: int, city: str | None = None
) -> list[Poi]:
    """active + rating 缺口 + QUNAR_CITY_SLUGS 覆盖城市，优先组打头。"""
    cities = [city] if city else list(QUNAR_CITY_SLUGS)
    with session_factory() as session:
        q = (
            session.query(Poi)
            .filter(Poi.status == "active", Poi.rating.is_(None), Poi.city.in_(cities))
            .order_by(_source_rank(), Poi.rating.desc().nullslast(), Poi.id)
            .limit(limit)
        )
        return q.all()


class _Target(NamedTuple):
    poi_id: object
    name: str
    city: str


# --- 匹配闸：列表页 (id,name) 对与名称变体互含 --------------------------------


def _mutual_hit(list_name: str, variants: list[str]) -> bool:
    """任一变体与列表名互含（各 ≥2 字）即放行，防同名异地靠城列表页兜底。"""
    ln = list_name.strip()
    for v in variants:
        v = v.strip()
        if len(v) >= 2 and len(ln) >= 2 and (v in ln or ln in v):
            return True
    return False


def match_targets(
    targets: list[_Target], candidates: list[tuple[str, str]]
) -> dict[_Target, str]:
    """targets × 列表 candidates → poi_id；互含闸通过才取，首个通过者。"""
    matched: dict[_Target, str] = {}
    for t in targets:
        variants = _variants(t.name)
        for list_name, qid in candidates:
            if _mutual_hit(list_name, variants):
                matched[t] = qid
                break
    return matched


# --- 网络层 --------------------------------------------------------------------


async def _fetch(client: httpx.AsyncClient, sem: asyncio.Semaphore, url: str):
    """429/5xx 指数退避重试；请求间 sleep 0.5-1s（并发 2 礼貌节奏）。
    重试耗尽或非可重试状态码原样返回 Response，由调用方计错误。"""
    for attempt in range(_MAX_ATTEMPTS):
        async with sem:
            r = await client.get(url)
            await asyncio.sleep(random.uniform(_SLEEP_MIN, _SLEEP_MAX))
        if r.status_code == 200:
            return r
        if r.status_code in _RETRYABLE_STATUS and attempt < _MAX_ATTEMPTS - 1:
            await asyncio.sleep(min(30.0, 2.0**attempt + random.random() * 2))
            continue
        return r
    raise RuntimeError("unreachable")


def _count_error(stats: dict, kind: str) -> None:
    stats["errors"] += 1
    stats["error_kinds"][kind] = stats["error_kinds"].get(kind, 0) + 1


# --- 写库：fill-empty-only，每行单独 commit ------------------------------------


def _write_row(factory, poi_id, rating: float | None, count: int | None) -> str:
    """返回 'rating' / 'count' / 'rating_count' / 'skip'。

    fill-empty-only：rating/rating_count 空才写；rating_source='qunar'
    仅在写入 rating 时打标（来源列归属 rating 本身，不冒充 count 溯源）。
    """
    with factory() as session:
        row = session.get(Poi, poi_id)
        if row is None:
            return "skip"
        wrote = "skip"
        if row.rating is None and rating is not None:
            row.rating = rating
            row.rating_source = "qunar"
            wrote = "rating"
        if row.rating_count is None and count is not None:
            row.rating_count = count
            wrote = "rating_count" if wrote != "rating" else "both"
        if wrote != "skip":
            session.commit()
        return wrote


# --- 详情页处理 ----------------------------------------------------------------


async def _process_detail(
    client,
    factory,
    sem,
    target: _Target,
    qunar_id: str,
    stats: dict,
    breaker: list[int],
) -> None:
    if breaker[0] >= _BREAKER_DETAIL_ERRORS:
        stats["skipped_by_breaker"] += 1
        return
    try:
        r = await _fetch(client, sem, _DETAIL_URL.format(poi_id=qunar_id))
    except Exception as exc:
        breaker[0] += 1
        logger.warning("qunar detail fetch failed id=%s: %s", qunar_id, exc)
        _count_error(stats, type(exc).__name__)
        stats["miss_ledger"].append((str(target.poi_id), target.name, "fetch_error"))
        return
    if r.status_code != 200:
        breaker[0] += 1
        _count_error(stats, f"HTTP{r.status_code}")
        stats["miss_ledger"].append(
            (str(target.poi_id), target.name, f"http_{r.status_code}")
        )
        return
    breaker[0] = 0  # 成功页清零连续异常计数
    rating, count = parse_detail_rating(r.text)
    rating, count = gate(rating, count)
    if rating is None and count is None:
        stats["no_parse"] += 1
        stats["miss_ledger"].append((str(target.poi_id), target.name, "no_parse"))
        return
    wrote = await asyncio.to_thread(_write_row, factory, target.poi_id, rating, count)
    if wrote == "skip":
        stats["skipped_filled"] += 1
        return
    if wrote in ("rating", "both"):
        stats["filled_rating"] += 1
    if wrote in ("count", "both"):
        stats["filled_count"] += 1
    stats["samples"].append(
        {"name": target.name, "city": target.city, "rating": rating, "count": count}
    )
    logger.info(
        "qunar rating %s (%s): rating=%s count=%s [%s]",
        target.name,
        target.city,
        rating,
        count,
        wrote,
    )


# --- 单城收割 ------------------------------------------------------------------


async def _collect_city(
    client, factory, sem, city: str, slug: str, targets: list[_Target], stats: dict
) -> None:
    """单城：列表最多翻 3 页建 candidates → 互含匹配 → 抓详情写库。

    确定性失败只试一次：匹配不到/详情解析不出均记 miss 台账后不再重试。
    """
    candidates: list[tuple[str, str]] = []
    seen_ids: set[str] = set()
    for page in range(1, _PAGES_PER_CITY_CAP + 1):
        try:
            r = await _fetch(client, sem, _LIST_URL.format(slug=slug, page=page))
        except Exception as exc:
            logger.warning(
                "qunar list fetch failed city=%s page=%s: %s", city, page, exc
            )
            _count_error(stats, type(exc).__name__)
            break
        stats["pages"] += 1
        if r.status_code != 200:
            _count_error(stats, f"HTTP{r.status_code}")
            break
        # 错误 slug 会 302 到 beijing 默认列表（duration 作业实测坑）：拒收整页
        items, locality = parse_list_page(r.text)
        if f"city={slug}" not in str(r.url) and not (
            locality and locality.removesuffix("市") == city
        ):
            logger.warning(
                "qunar list city mismatch: %s(%s) landed on %s", city, slug, r.url
            )
            _count_error(stats, "city_redirect")
            break
        fresh = [(n, pid) for n, pid in items if pid not in seen_ids]
        if not fresh:
            break  # 翻页尽头
        seen_ids.update(pid for _, pid in fresh)
        candidates.extend(fresh)
    matched = match_targets(targets, candidates)
    stats["matched"] += len(matched)
    breaker = [0]
    for t in targets:
        qid = matched.get(t)
        if qid is None:
            stats["no_match"] += 1
            stats["miss_ledger"].append((str(t.poi_id), t.name, "no_list_match"))
        else:
            await _process_detail(client, factory, sem, t, qid, stats, breaker)
            if breaker[0] >= _BREAKER_DETAIL_ERRORS:
                logger.warning("detail breaker tripped, stop batch")
                stats["stop"] = "detail_errors"
                return


async def enrich(factory, *, limit: int, city: str | None = None) -> dict:
    stats = {
        "targets": 0,
        "cities": 0,
        "pages": 0,
        "matched": 0,
        "no_match": 0,
        "filled_rating": 0,
        "filled_count": 0,
        "no_parse": 0,
        "skipped_filled": 0,
        "skipped_by_breaker": 0,
        "errors": 0,
        "error_kinds": {},
        "stop": None,
        "samples": [],
        "miss_ledger": [],
    }
    rows = select_targets(factory, limit=limit, city=city)
    stats["targets"] = len(rows)
    by_city: dict[str, list[_Target]] = {}
    for r in rows:
        name = (r.name_zh or "").strip()
        if not name:
            continue
        c = (r.city or "").strip()
        by_city.setdefault(c, []).append(_Target(r.id, name, c))
    sem = asyncio.Semaphore(_CONCURRENCY)
    async with httpx.AsyncClient(
        headers=_HEADERS, timeout=30, follow_redirects=True
    ) as client:
        for c, targets in by_city.items():
            slug = QUNAR_CITY_SLUGS.get(c)
            if not slug:
                for t in targets:
                    stats["no_match"] += 1
                    stats["miss_ledger"].append((str(t.poi_id), t.name, "city_no_slug"))
                continue
            stats["cities"] += 1
            await _collect_city(client, factory, sem, c, slug, targets, stats)
            if stats["stop"]:
                break
    return stats


# --- 台账 -----------------------------------------------------------------------


def write_miss_ledger(path: Path, misses: list[tuple[str, str, str]]) -> None:
    if not misses:
        return
    lines = [f"{pid}\t{name}\t{reason}\n" for pid, name, reason in misses]
    with open(path, "a", encoding="utf-8") as f:
        f.writelines(lines)


# --- CLI ------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Qunar rating enrichment (fill-empty-only, single-source qunar)"
    )
    parser.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)
    parser.add_argument("--city", type=str, default=None, help="单城筛选（city 名）")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    factory = get_session_factory()
    stats = asyncio.run(enrich(factory, limit=args.limit, city=args.city))
    miss_ledger = stats.pop("miss_ledger")
    ledger = Path(__file__).resolve().parent / "qunar_rating_missed.txt"
    write_miss_ledger(ledger, miss_ledger)
    print(json.dumps(stats, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
