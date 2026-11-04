"""POI 富化·百度地图地点检索（六列一网打尽，确定性大厂源）。

背景（2026-10-25）：用户提供百度地图 key（.env BAIDU_MAP_KEY）。
scope=2 的 detail_info 携带 overall_rating/comment_num/shop_hours/
new_alias，配合 result 级 telephone/area——一次调用覆盖六列：
phone / district / opening_hours / rating / rating_count / name_aliases。
用户明示有量限制：并发压 2、配额错误（status 401/402）首撞熔断。

匹配闸门：候选 name 与名称变体互含（防同名异地）；只取首个通过者。
写库：逐列只填空；来源标记 hours_source/rating_source='baidu'
（phone/district/name_aliases 无 source 列，溯源靠作业日志）。

用法：
    python -m app.jobs.enrich_baidu_map [--limit 200] [--concurrency 2] [--dry-run]
"""

import argparse
import asyncio
import json
import logging
import re
import sys
from typing import NamedTuple

import httpx
from sqlalchemy import or_

from app.db import get_session_factory
from app.models import Poi

logger = logging.getLogger(__name__)

_DEFAULT_LIMIT = 200
_DEFAULT_CONCURRENCY = 2
_API = "https://api.map.baidu.com/place/v2/search"
_QUOTA_STATUSES = {401, 402, 302}  # 并发超限 / 总配额超限 / 天配额超限


_SEG_SEP_RE = re.compile(r"[·・•\-－—–~～/|]")

# 省/州/县/区/市/旗 行政区前缀（可连续出现多层，如
# 「黔南布依族苗族自治州荔波县樟江景区」）。2026-11-04：原正则只剥一层，
# 5A/4A 名录行大面积留下「荔波县樟江景区」这类带县名的变体，回源必空。
_ADMIN_PREFIX_RE = re.compile(
    r"^[\u4e00-\u9fa5]{1,10}?(?:自治州|自治县|自治旗|地区|盟|区|县|市|旗)"
)
_SUFFIX_RE = re.compile(
    r"(风景名胜区|旅游景区|旅游区|风景区|度假区|景区|遗址公园|湿地公园|"
    r"森林公园|地质公园|乐园|公园)$"
)


def _strip_admin_prefixes(name: str) -> list[str]:
    """逐层剥离行政区前缀，返回每剥一层的中间名（不含原名）。

    只剥剩余长度 ≥3 的前缀，避免把「大理古城」剥成「古城」这类丢信息。
    """
    out: list[str] = []
    cur = name
    while True:
        m = _ADMIN_PREFIX_RE.match(cur)
        if not m:
            break
        rest = cur[len(m.group(0)) :]
        if len(rest) < 3:
            break
        out.append(rest)
        cur = rest
    return out


def _variants(name: str) -> list[str]:
    out = [name]
    out.extend(_strip_admin_prefixes(name))
    # 对每层剥完的名字再去景区类尾缀，逐层叠加（各层都留变体）。
    # 尾缀也可能叠两层（「世界雕塑公园景区」→「世界雕塑公园」→「世界雕塑」）。
    for base in list(out):
        cur = base
        while True:
            core = _SUFFIX_RE.sub("", cur)
            if core == cur or len(core) < 2:
                break
            if core not in out:
                out.append(core)
            cur = core
    # 组合名分段（2026-11-04 台账样本：皖南古村落西递和宏村、
    # 钟山风景名胜区－中山陵园风景区）：分段名各自检索命中率更高。
    # 只按显式分隔符切（不用「和」——太和殿/中和殿会被切坏）。
    for base in list(out):
        for seg in _SEG_SEP_RE.split(base):
            seg = seg.strip()
            if len(seg) >= 2 and seg not in out:
                out.append(seg)
                core = _SUFFIX_RE.sub("", seg)
                if len(core) >= 2 and core not in out:
                    out.append(core)
    # 前缀剥离可能把分段名剥成「－中山陵园风景区」这类带前导分隔符的脏
    # 变体——统一去首尾分隔符/空白，别拿脏关键词白烧检索配额。
    cleaned = [v.strip("·・•-－—–~～/| \t") for v in out]
    return [v for v in dict.fromkeys(cleaned) if v]


def _match_name(name: str, variants: list[str]) -> bool:
    n = (name or "").replace(" ", "")
    return any(
        v.replace(" ", "") and (v.replace(" ", "") in n or n in v.replace(" ", ""))
        for v in variants
    )


def _clean_tel(tel) -> str | None:
    if not tel:
        return None
    t = str(tel).strip()
    return t if re.fullmatch(r"[\d\-\(\)（）\s,，/]{7,30}", t) else None


def _parse_aliases(raw) -> list[str]:
    """new_alias 形状未知（str/list），防御性归一为别名列表。"""
    if isinstance(raw, str):
        raw = re.split(r"[,，;；/|]", raw)
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for a in raw:
        if not isinstance(a, str):
            continue
        a = a.strip()
        if 2 <= len(a) <= 40 and a not in out:
            out.append(a)
        if len(out) >= 5:
            break
    return out


def select_targets(session_factory, *, limit: int) -> list[Poi]:
    with session_factory() as session:
        return (
            session.query(Poi)
            .filter(
                Poi.status == "active",
                Poi.city.isnot(None),
                Poi.city != "",
                or_(
                    Poi.phone.is_(None),
                    Poi.district.is_(None),
                    Poi.opening_hours.is_(None),
                    Poi.rating.is_(None),
                    Poi.name_aliases.is_(None),
                ),
            )
            .order_by(Poi.rating.desc().nullslast(), Poi.id)
            .limit(limit)
            .all()
        )


class _Target(NamedTuple):
    poi_id: object
    name: str
    city: str


def _search(
    client: httpx.Client, key: str, keyword: str, city: str, *, page_size: int = 20
) -> dict:
    r = client.get(
        _API,
        params={
            "query": keyword,
            "region": city,
            "city_limit": "true",
            "output": "json",
            "scope": 2,
            "page_size": page_size,
            "ak": key,
        },
    )
    r.raise_for_status()
    d = r.json()
    if d.get("status") == 0:
        return d
    err = RuntimeError(f"baidu status={d.get('status')} {d.get('message')}")
    err.status = d.get("status")  # type: ignore[attr-defined]
    raise err


def _best_hit(results: list, variants: list[str]) -> dict | None:
    """在单次检索返回的候选里挑第一个名称命中变体的行（配额友好）。"""
    for cand in results or []:
        if isinstance(cand, dict) and _match_name(cand.get("name", ""), variants):
            return cand
    return None


def _write_row(factory, poi_id, hit: dict) -> list[str]:
    written: list[str] = []
    with factory() as session:
        row = session.get(Poi, poi_id)
        if row is None:
            return written
        tel = _clean_tel(hit.get("telephone"))
        if row.phone is None and tel:
            row.phone = tel[:50]
            written.append("phone")
        _area_raw = hit.get("area")
        area = _area_raw.strip() if isinstance(_area_raw, str) else ""
        if row.district is None and area:
            row.district = area[:50]
            written.append("district")
        di = hit.get("detail_info") or {}
        # shop_hours 偶为非字符串（list/dict）：or 短路会吞掉合法的
        # regular_open_hour 字符串——改为两候选里取第一个字符串.
        _hours_cands = (di.get("shop_hours"), di.get("regular_open_hour"))
        _hours_raw = next((v for v in _hours_cands if isinstance(v, str)), None)
        if _hours_raw is None and any(_hours_cands):
            logger.debug("baidu 营业时间候选均非字符串，弃用: %r", _hours_cands)
        hours = _hours_raw.strip() if _hours_raw else ""
        if row.opening_hours is None and hours:
            row.opening_hours = hours[:200]
            row.hours_source = "baidu"
            written.append("opening_hours")
        rv = di.get("overall_rating")
        try:
            rv = float(rv) if rv not in (None, "") else None
        except (TypeError, ValueError):
            rv = None
        if row.rating is None and rv is not None and 0 <= rv <= 5:
            row.rating = rv
            row.rating_source = "baidu"
            written.append("rating")
        cn = di.get("comment_num")
        if row.rating_count is None and isinstance(cn, int) and 0 <= cn <= 10_000_000:
            row.rating_count = cn
            written.append("rating_count")
        aliases = _parse_aliases(di.get("new_alias"))
        if row.name_aliases is None and aliases:
            row.name_aliases = aliases
            written.append("name_aliases")
        if written:
            session.commit()
    return written


async def _process_row(
    client: httpx.Client,
    key: str,
    factory,
    t: _Target,
    sem: asyncio.Semaphore,
    stats: dict,
) -> None:
    variants = _variants(t.name)
    async with sem:
        hit = None
        try:
            # 一次检索取 20 个候选 + 本地变体匹配（旧实现逐变体各发一
            # 次，no_match 行最贵；百度地点检索日配额仅百级，省着用）。
            d = await asyncio.to_thread(_search, client, key, variants[0], t.city)
            hit = _best_hit(d.get("results") or [], variants)
            if hit is None and len(variants) > 1:
                d = await asyncio.to_thread(
                    _search, client, key, variants[-1], t.city
                )
                hit = _best_hit(d.get("results") or [], variants)
        except Exception as exc:
            st = getattr(exc, "status", None)
            if st in _QUOTA_STATUSES:
                stats["stop"] = f"quota:{st}"
                return
            stats["errors"] += 1
            stats["error_kinds"][type(exc).__name__] = (
                stats["error_kinds"].get(type(exc).__name__, 0) + 1
            )
            key = f"status={st}" if st is not None else type(exc).__name__
            stats.setdefault("error_statuses", {})
            stats["error_statuses"][key] = stats["error_statuses"].get(key, 0) + 1
            if len(stats.get("error_samples", [])) < 3:
                stats.setdefault("error_samples", []).append(
                    {"name": t.name, "msg": str(exc)[:80]}
                )
            return
    if not hit:
        stats["no_match"] += 1
        return
    stats["matched"] += 1
    written = await asyncio.to_thread(_write_row, factory, t.poi_id, hit)
    for col in written:
        stats["filled"][col] = stats["filled"].get(col, 0) + 1
    if written and len(stats["samples"]) < 10:
        di = hit.get("detail_info") or {}
        stats["samples"].append(
            {
                "name": t.name,
                "city": t.city,
                "cols": written,
                "title": hit.get("name"),
                "tel": hit.get("telephone"),
                "area": hit.get("area"),
                "rating": di.get("overall_rating"),
                "hours": (di.get("shop_hours") or "")[:30],
                "aliases": _parse_aliases(di.get("new_alias")),
            }
        )


async def enrich(factory, key: str, *, limit: int, concurrency: int) -> dict:
    stats = {
        "targets": 0,
        "matched": 0,
        "no_match": 0,
        "errors": 0,
        "error_kinds": {},
        "filled": {},
        "samples": [],
        "stop": None,
    }
    rows = select_targets(factory, limit=limit)
    stats["targets"] = len(rows)
    targets = [
        _Target(r.id, (r.name_zh or "").strip(), (r.city or "").strip())
        for r in rows
        if (r.name_zh or "").strip() and (r.city or "").strip()
    ]
    limits = httpx.Limits(max_connections=concurrency)
    with httpx.Client(
        headers={"User-Agent": "chinatrip-enrich/0.1"}, timeout=15, limits=limits
    ) as client:
        sem = asyncio.Semaphore(max(1, concurrency))
        await asyncio.gather(
            *(_process_row(client, key, factory, t, sem, stats) for t in targets)
        )
    return stats


# --- CLI --------------------------------------------------------------------


def dry_run(session_factory, *, limit: int) -> None:
    rows = select_targets(session_factory, limit=limit)
    print(json.dumps({"dry_run": True, "targets": len(rows)}, ensure_ascii=True))


def _key_from_env() -> str:
    for line in open(".env", encoding="utf-8"):
        if line.startswith("BAIDU_MAP_KEY="):
            return line.split("=", 1)[1].strip()
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Baidu map enrichment (6 columns, deterministic)"
    )
    parser.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)
    parser.add_argument("--concurrency", type=int, default=_DEFAULT_CONCURRENCY)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    factory = get_session_factory()
    if args.dry_run:
        dry_run(factory, limit=args.limit)
        return 0
    key = _key_from_env()
    if not key:
        print(json.dumps({"error": "BAIDU_MAP_KEY missing in .env"}, ensure_ascii=True))
        return 1
    stats = asyncio.run(
        enrich(factory, key, limit=args.limit, concurrency=args.concurrency)
    )
    print(json.dumps(stats, ensure_ascii=True))
    return 2 if stats.get("stop") else 0


if __name__ == "__main__":
    sys.exit(main())
