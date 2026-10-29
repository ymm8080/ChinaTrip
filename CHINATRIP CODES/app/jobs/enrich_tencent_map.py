"""POI 富化·腾讯地图地点检索（phone/district，确定性大厂源）。

背景（2026-10-25）：用户申请腾讯位置服务 WebServiceAPI key（存 .env
TENCENT_MAP_KEY），授权用于补 phone/district 两列——二者均无 _source
列，溯源靠本作业日志与 stats。用户明示有量限制：并发压 2、首撞配额
错误（status 120）即熔断整轮。

目标行：active 且 phone/district 任一为空、city 非空。
检索：keyword=名称变体（复用 ctrip 变体思路），boundary=region(城市,0)。
匹配闸门：候选 title 与变体互含才收（防同名异地）；只取首个通过者。
写库：逐列只填空；tel 空串不写；district 取 ad_info.district（含"区"
后缀，与 ctrip 风格一致）。

用法：
    python -m app.jobs.enrich_tencent_map [--limit 200] [--concurrency 2] [--dry-run]
"""

import argparse
import asyncio
import json
import re
import sys
from typing import NamedTuple

import httpx
from sqlalchemy import or_

from app.db import get_session_factory
from app.models import Poi

_DEFAULT_LIMIT = 200
_DEFAULT_CONCURRENCY = 2
_API = "https://apis.map.qq.com/ws/place/v1/search"
_QUOTA_STATUSES = {120, 121}  # 120 超并发/QPS；121 日配额到顶


def _variants(name: str) -> list[str]:
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
    if len(core) >= 2 and core not in out:
        out.append(core)
    return list(dict.fromkeys(out))


def _match_title(title: str, variants: list[str]) -> bool:
    """候选标题与任一变体互含（去空格粗归一）。"""
    t = (title or "").replace(" ", "")
    return any(
        v.replace(" ", "") and (v.replace(" ", "") in t or t in v.replace(" ", ""))
        for v in variants
    )


def select_targets(session_factory, *, limit: int) -> list[Poi]:
    with session_factory() as session:
        return (
            session.query(Poi)
            .filter(
                Poi.status == "active",
                Poi.city.isnot(None),
                Poi.city != "",
                or_(Poi.phone.is_(None), Poi.district.is_(None)),
            )
            .order_by(Poi.rating.desc().nullslast(), Poi.id)
            .limit(limit)
            .all()
        )


class _Target(NamedTuple):
    poi_id: object
    name: str
    city: str


def _search(client: httpx.Client, key: str, keyword: str, city: str) -> list[dict]:
    r = client.get(
        _API,
        params={
            "keyword": keyword,
            "boundary": f"region({city},0)",
            "page_size": 5,
            "page_index": 1,
            "key": key,
        },
    )
    r.raise_for_status()
    d = r.json()
    if d.get("status") == 0:
        return d.get("data") or []
    err = RuntimeError(f"tencent status={d.get('status')} {d.get('message')}")
    err.status = d.get("status")  # type: ignore[attr-defined]
    raise err


def _write_row(factory, poi_id, *, tel: str | None, district: str | None) -> list[str]:
    written: list[str] = []
    with factory() as session:
        row = session.get(Poi, poi_id)
        if row is None:
            return written
        if row.phone is None and tel:
            row.phone = tel[:50]
            written.append("phone")
        if row.district is None and district:
            row.district = district[:50]
            written.append("district")
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
            for v in variants:
                data = await asyncio.to_thread(_search, client, key, v, t.city)
                for cand in data:
                    if _match_title(cand.get("title", ""), variants):
                        hit = cand
                        break
                if hit:
                    break
        except Exception as exc:
            st = getattr(exc, "status", None)
            if st in _QUOTA_STATUSES:
                stats["stop"] = f"quota:{st}"  # 首撞熔断
                return
            stats["errors"] += 1
            stats["error_kinds"][type(exc).__name__] = (
                stats["error_kinds"].get(type(exc).__name__, 0) + 1
            )
            return
    if not hit:
        stats["no_match"] += 1
        return
    stats["matched"] += 1
    tel = (hit.get("tel") or "").strip() or None
    district = ((hit.get("ad_info") or {}).get("district") or "").strip() or None
    if not tel and not district:
        stats["no_fields"] += 1
        return
    written = await asyncio.to_thread(
        _write_row, factory, t.poi_id, tel=tel, district=district
    )
    for col in written:
        stats["filled"][col] = stats["filled"].get(col, 0) + 1
    if written and len(stats["samples"]) < 10:
        stats["samples"].append(
            {
                "name": t.name,
                "city": t.city,
                "cols": written,
                "title": hit.get("title"),
                "tel": tel,
                "district": district,
            }
        )


async def enrich(factory, key: str, *, limit: int, concurrency: int) -> dict:
    stats = {
        "targets": 0,
        "matched": 0,
        "no_match": 0,
        "no_fields": 0,
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
    for r in rows[:5]:
        print(
            json.dumps(
                {
                    "city": r.city,
                    "name": r.name_zh,
                    "variants": _variants((r.name_zh or "").strip())[:3],
                },
                ensure_ascii=True,
            )
        )


def _key_from_env() -> str:
    for line in open(".env", encoding="utf-8"):
        if line.startswith("TENCENT_MAP_KEY="):
            return line.split("=", 1)[1].strip()
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Tencent map enrichment (phone/district)"
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
        print(
            json.dumps({"error": "TENCENT_MAP_KEY missing in .env"}, ensure_ascii=True)
        )
        return 1
    stats = asyncio.run(
        enrich(factory, key, limit=args.limit, concurrency=args.concurrency)
    )
    print(json.dumps(stats, ensure_ascii=True))
    return 2 if stats.get("stop") else 0


if __name__ == "__main__":
    sys.exit(main())
