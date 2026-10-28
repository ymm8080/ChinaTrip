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
import re
import sys
from typing import NamedTuple

import httpx
from sqlalchemy import or_

from app.db import get_session_factory
from app.models import Poi

_DEFAULT_LIMIT = 200
_DEFAULT_CONCURRENCY = 2
_API = "https://api.map.baidu.com/place/v2/search"
_QUOTA_STATUSES = {401, 402, 302}  # 并发超限 / 总配额超限 / 天配额超限


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


def _search(client: httpx.Client, key: str, keyword: str, city: str) -> dict:
    r = client.get(
        _API,
        params={
            "query": keyword,
            "region": city,
            "city_limit": "true",
            "output": "json",
            "scope": 2,
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
        area = (hit.get("area") or "").strip()
        if row.district is None and area:
            row.district = area[:50]
            written.append("district")
        di = hit.get("detail_info") or {}
        hours = (di.get("shop_hours") or di.get("regular_open_hour") or "").strip()
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
            for v in variants:
                d = await asyncio.to_thread(_search, client, key, v, t.city)
                for cand in d.get("results") or []:
                    if _match_name(cand.get("name", ""), variants):
                        hit = cand
                        break
                if hit:
                    break
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
