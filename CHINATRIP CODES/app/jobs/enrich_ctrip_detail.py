"""POI 富化·携程详情页确定性行（消费 CtripHoursReader.detail_fields_for）。

背景（2026-10-25）：GLM coding 端点静默忽略 web_search 工具（探针实测
模型自述无搜索能力），"LLM+联网"路不存在；携程详情页是建议游玩时长/
门票/点评标签/开放时间的确定性在线来源，解析器已由 0009 流实现
（app/services/ctrip_hours.py，本作业只消费不改它）。

目标行：active 且 5 个富化列任一为空，城市须在 CITY_SLUGS 覆盖内
（其余城市 CtripHoursReader 直接 miss，不浪费请求）。选行仍按
unesco/5a/amap 优先 + rating 降序——规划器最先挑出的行先富化。

铁律：
  * 逐列只填空——写前复查该列仍为空才写该列，来源标记 *_source='ctrip'；
  * 数值过闸门（时长 15-600 分 / 门票 0-2000 元 / 评分 0-5 / 点评数
    ≤1000 万 / 标签≤8 个且每个≤20 字），不合格当 None 处理；
  * reader 自带目录页与并发硬顶（4 页/查询、12 页/城），本作业不放大；
  * 单行失败只计数，不中断。

用法：
    python -m app.jobs.enrich_ctrip_detail [--limit 100] [--concurrency 8] [--dry-run]
"""

import argparse
import asyncio
import json
import re
import sys
from typing import NamedTuple

from sqlalchemy import case, or_

from app.db import get_session_factory
from app.models import Poi
from app.services import ctrip_hours as _ch
from app.services.ctrip_hours import (
    CITY_SLUGS,
    CtripHoursReader,
    parse_detail_fields,
    parse_hours,
)

_DEFAULT_LIMIT = 100
_DEFAULT_CONCURRENCY = 8
_DURATION_MIN, _DURATION_MAX = 15, 600
_TICKET_MAX = 2000

# BFS 发现的城市 slug（discover_ctrip_slugs.py 产出）；运行时注入
# ctrip_hours.CITY_SLUGS（模块全局，reader 每次调用现查，不改其文件）
_SLUG_CACHE = "../DESIGN/ctrip_city_slugs.json"
_BIG_CITIES = frozenset(CITY_SLUGS)  # 9 大城用大目录预算，小城给小预算


def _load_extra_slugs() -> dict[str, str]:
    try:
        with open(_SLUG_CACHE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


# --- 详情页扩展解析（同页多榨，零额外请求；对真实页样本 2026-10-25） ------

_TEL_RE = re.compile(r'"telephoneList":\[\s*"([^"]+)"')
_ADDR_RE = re.compile(r'"address":"([^"]{2,80})"')
_DISTRICT_RE = re.compile(r"([\u4e00-\u9fa5]{2,8}?(?:区|县))")
_IMAGE_LIST_RE = re.compile(r'"imageList":\[(.*?)\]')


def _extract_extra(html: str) -> dict:
    """从详情页 HTML 的内嵌 JSON 状态里榨 telephone/district/photos。"""
    out: dict = {}
    m = _TEL_RE.search(html)
    if m:
        tel = m.group(1).lstrip("+").removeprefix("86")
        if re.fullmatch(r"[\d\-]{7,20}", tel):
            out["telephone"] = tel
    a = _ADDR_RE.search(html)
    if a:
        # 剥掉前缀行政区（"重庆市九龙坡区…"→"九龙坡区"）；无"市"分隔则原样找
        addr = a.group(1).split("市", 1)[-1]
        dm = re.search(r"([\u4e00-\u9fa5]{2,8}(?:区|县))", addr)
        if dm:
            out["district"] = dm.group(1)
    im = _IMAGE_LIST_RE.search(html)
    if im:
        urls = re.findall(
            r'"(https://dimg\d*\.c-ctrip\.com/images/[^"]+?\.(?:jpg|png|jpeg)(?:\?[^"]*)?)"',
            im.group(1),
        )
        out["photos"] = [{"title": "", "url": u} for u in dict.fromkeys(urls)][:8]
    return out


class RichCtripReader(CtripHoursReader):
    """拦截 _detail_fields 的原始 HTML，在基类字段上多榨电话/区县/图片。

    取页逻辑与基类一致（同 URL 同缓存键），只是解析多走一步——
    不改 ctrip_hours.py 的前提下拿到 raw HTML 的唯一干净缝。
    """

    async def _detail_fields(self, url: str) -> dict | None:
        if url in self._details:
            return self._details[url]
        try:
            async with self._slots():
                r = await self._client.get(url)
        except Exception:
            return None
        fields: dict | None = None
        if r.status_code == 200:
            html = r.text
            fields = {"opening_hours": parse_hours(html), **parse_detail_fields(html)}
            fields.update(_extract_extra(html))
        self._details[url] = fields
        return fields


def _gate_int(v, lo: int, hi: int) -> int | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    iv = int(v)
    return iv if iv == v and lo <= iv <= hi else None


def _gate_tags(v) -> list[str]:
    if not isinstance(v, list):
        return []
    out: list[str] = []
    for t in v:
        if isinstance(t, str) and 1 <= len(t.strip()) <= 20 and t.strip() not in out:
            out.append(t.strip())
        if len(out) >= 8:
            break
    return out


# --- 目标行选取 -------------------------------------------------------------


def _source_rank():
    whens = [
        (Poi.source == src, rank)
        for rank, src in enumerate(("unesco", "5a", "amap", "chinatravel", "osm"))
    ]
    return case(*whens, else_=5)


_TARGET_COLS = (
    Poi.suggested_duration_min.is_(None),
    Poi.ticket_price_min.is_(None),
    Poi.review_tags.is_(None),
    Poi.opening_hours.is_(None),
    Poi.rating.is_(None),
)


def select_targets(session_factory, *, limit: int) -> list[Poi]:
    slugs = {**CITY_SLUGS, **_load_extra_slugs()}
    with session_factory() as session:
        return (
            session.query(Poi)
            .filter(Poi.status == "active", Poi.city.in_(list(slugs)))
            .filter(or_(*_TARGET_COLS))
            .order_by(_source_rank(), Poi.rating.desc().nullslast(), Poi.id)
            .limit(limit)
            .all()
        )


class _Target(NamedTuple):
    poi_id: object
    name: str
    city: str


def _variants(name: str) -> list[str]:
    """匹配变体：原名 → 剥前缀行政区 → 再剥尾缀类型词。

    实测（重庆 20 行 2026-10-25）：200 页目录饱和 + 变体把命中率
    从 ~7% 抬到 50%——'酉阳土家族苗族自治县桃花源旅游景区' 这类
    长名靠 '桃花源旅游景区' 级别的变体才对得上携程目录名。
    """
    out = [name]
    m = re.search(r"^[\u4e00-\u9fa5]{1,10}?(?:自治州|自治县|区|县|市|旗)", name)
    if m and len(name) - len(m.group(0)) >= 3:
        out.append(name[len(m.group(0)) :])
    core = re.sub(
        r"(风景名胜区|旅游景区|旅游区|风景区|度假区|景区|遗址公园|湿地公园|"
        r"森林公园|地质公园|乐园|公园)$",
        "",
        out[-1],
    )
    if len(core) >= 3 and core not in out:
        out.append(core)
    return list(dict.fromkeys(out))


# --- 单行处理 ---------------------------------------------------------------


def _write_row(factory, poi_id, f: dict) -> list[str]:
    """逐列只填空写库；返回实际写入的列名清单。"""
    written: list[str] = []
    with factory() as session:
        row = session.get(Poi, poi_id)
        if row is None:
            return written
        if row.phone is None and f.get("telephone"):
            row.phone = str(f["telephone"])[:50]
            written.append("phone")
        if row.district is None and f.get("district"):
            row.district = str(f["district"])[:50]
            written.append("district")
        if row.photos is None and f.get("photos"):
            row.photos = f["photos"]
            written.append("photos")
        if row.opening_hours is None and f.get("opening_hours"):
            row.opening_hours = str(f["opening_hours"]).strip()[:200]
            row.hours_source = "ctrip"
            written.append("opening_hours")
        d = _gate_int(f.get("suggested_duration_min"), _DURATION_MIN, _DURATION_MAX)
        if row.suggested_duration_min is None and d is not None:
            row.suggested_duration_min = d
            row.duration_source = "ctrip"
            written.append("duration")
        tmin = _gate_int(f.get("ticket_price_min"), 0, _TICKET_MAX)
        tmax = _gate_int(f.get("ticket_price_max"), 0, _TICKET_MAX)
        if row.ticket_price_min is None and tmin is not None:
            row.ticket_price_min = tmin
            row.ticket_price_max = tmax if (tmax is not None and tmax >= tmin) else tmin
            row.ticket_source = "ctrip"
            written.append("ticket")
        tags = _gate_tags(f.get("review_tags"))
        if row.review_tags is None and tags:
            row.review_tags = tags
            row.review_tags_source = "ctrip"
            written.append("review_tags")
        r = f.get("rating")
        if row.rating is None and isinstance(r, (int, float)) and 0 <= r <= 5:
            row.rating = float(r)
            row.rating_source = "ctrip"
            written.append("rating")
        session.commit()
    return written


async def _process_row(
    reader: CtripHoursReader, factory, t: _Target, sem: asyncio.Semaphore, stats: dict
) -> None:
    async with sem:
        try:
            fields = None
            for v in _variants(t.name):
                fields = await reader.detail_fields_for(t.city, v)
                if fields:
                    break
        except Exception as exc:
            stats["errors"] += 1
            stats["error_kinds"][type(exc).__name__] = (
                stats["error_kinds"].get(type(exc).__name__, 0) + 1
            )
            return
    if not fields:
        stats["no_page"] += 1
        return
    stats["page_hits"] += 1
    written = await asyncio.to_thread(_write_row, factory, t.poi_id, fields)
    for col in written:
        stats["filled"][col] = stats["filled"].get(col, 0) + 1
    if written:
        stats["samples"].append(
            {
                "name": t.name,
                "city": t.city,
                "cols": written,
                "duration_min": _gate_int(
                    fields.get("suggested_duration_min"), _DURATION_MIN, _DURATION_MAX
                ),
                "ticket": _gate_int(fields.get("ticket_price_min"), 0, _TICKET_MAX),
                "hours": str(fields.get("opening_hours") or "")[:40],
                "tags": _gate_tags(fields.get("review_tags")),
            }
        )


async def enrich(
    factory,
    *,
    limit: int,
    concurrency: int,
    max_lookup_pages: int = 8,
    max_city_pages: int = 60,
) -> dict:
    stats = {
        "targets": 0,
        "no_page": 0,
        "page_hits": 0,
        "errors": 0,
        "error_kinds": {},
        "filled": {},
        "samples": [],
        "reader_caps": {
            "max_pages_per_lookup": max_lookup_pages,
            "max_total_pages_per_city": max_city_pages,
        },
    }
    rows = select_targets(factory, limit=limit)
    stats["targets"] = len(rows)
    targets = [
        _Target(r.id, (r.name_zh or "").strip(), (r.city or "").strip())
        for r in rows
        if (r.name_zh or "").strip()
    ]
    extra = _load_extra_slugs()
    _ch.CITY_SLUGS.update(extra)  # 运行时扩图：reader 每次调用现查模块全局
    stats["cities"] = {"big": len(_BIG_CITIES), "total": len(_ch.CITY_SLUGS)}
    # 大城吃满目录预算；小城（多为一两行）给小预算防浪费
    reader_big = RichCtripReader(
        max_pages_per_lookup=max_lookup_pages, max_total_pages_per_city=max_city_pages
    )
    reader_small = RichCtripReader(max_pages_per_lookup=4, max_total_pages_per_city=10)
    sem = asyncio.Semaphore(max(1, concurrency))
    await asyncio.gather(
        *(
            _process_row(
                reader_big if t.city in _BIG_CITIES else reader_small,
                factory,
                t,
                sem,
                stats,
            )
            for t in targets
        )
    )
    return stats


# --- CLI --------------------------------------------------------------------


def dry_run(session_factory, *, limit: int) -> None:
    rows = select_targets(session_factory, limit=limit)
    print(json.dumps({"dry_run": True, "targets": len(rows)}, ensure_ascii=True))
    for r in rows[:5]:
        rating = float(r.rating) if r.rating is not None else None
        print(
            json.dumps(
                {
                    "source": r.source,
                    "city": r.city,
                    "name": r.name_zh,
                    "rating": rating,
                },
                ensure_ascii=True,
            )
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ctrip detail enrichment (deterministic)"
    )
    parser.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)
    parser.add_argument("--concurrency", type=int, default=_DEFAULT_CONCURRENCY)
    parser.add_argument(
        "--max-city-pages",
        type=int,
        default=200,
        help="CtripHoursReader directory cap per city (default 200)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    factory = get_session_factory()
    if args.dry_run:
        dry_run(factory, limit=args.limit)
        return 0
    # 锁：巡检 agent 与主会话可能同时起本作业；锁新鲜（<90min）则让位
    import os
    import time

    lock = "../DESIGN/ctrip_enrich.lock"
    try:
        if time.time() - os.path.getmtime(lock) < 90 * 60:
            print(json.dumps({"skipped": "lock_fresh"}))
            return 0
    except OSError:
        pass
    with open(lock, "w", encoding="utf-8") as fh:
        fh.write(str(time.time()))
    try:
        stats = asyncio.run(
            enrich(
                factory,
                limit=args.limit,
                concurrency=args.concurrency,
                max_city_pages=args.max_city_pages,
            )
        )
        print(json.dumps(stats, ensure_ascii=True))
        return 0
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
