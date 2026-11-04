"""营业时间/评分日批驱动（ops）：双引擎逐行收割 + miss 台账防重烧。

背景（2026-11-03 用户拍板「选对源、填到全完成」）：美团/点评无开放数据
API；携程详情页 PoC 目录端点 2026-11-03 午后变质（slug 闸已防污染，
通道下线待观察）；amap v5 detail 对本库 97% 行无 business 块。可规模化
的确定性源剩两条，各自日配额有限：

- baidu 引擎：place v2 scope=2 的 overall_rating/shop_hours/shop 电话，
  ~100 次/日（status 401/402/302 首撞即停）；
- amap 引擎：v5 place/text show_fields=business（opentime_week/rating，
  实测对本库有效：refresh 侧已填 1,583 行），个人搜索池 5,000/月
  （≈166/日，与 refresh_pois/坐标链共享；配额尽或 WAF punish 即停）。

共同纪律（照 backfill_coords_driver 模式）：
- 目标行：active + 有 city + hours 或 rating 为空，剔除本引擎台账行；
- 选行按**既有优先级序列**（unesco→5a→博物馆系→artmuseum→amap→
  chinatravel→osm，与 enrich_ctrip_detail._source_rank 同序）；
- 台账 ops/fill_hours_rating_missed.txt（baidu）/
  fill_hours_rating_missed_amap.txt：确定性失败（no_match/无目标字段）
  只试一次，配额永远花在新行上；两引擎台账分开——baidu 没有的
  某一行 amap 仍可能命中；
- 配额/WAF 首撞即停，未尝试行不入台账，次日续跑（fill-empty-only 无损）。

用法：
    python ops/fill_hours_rating_driver.py --engine baidu [--limit 120]
    python ops/fill_hours_rating_driver.py --engine amap  [--limit 150]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import get_session_factory  # noqa: E402
from app.models import Poi  # noqa: E402

_OPS = Path(__file__).resolve().parent
MISS_FILES = {
    "baidu": _OPS / "fill_hours_rating_missed.txt",
    "amap": _OPS / "fill_hours_rating_missed_amap.txt",
}

_QUOTA_STATUSES = {401, 402, 302}


def _load_missed(engine: str) -> dict[str, str]:
    path = MISS_FILES[engine]
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split(None, 1)
        if parts:
            out[parts[0]] = parts[1] if len(parts) > 1 else ""
    return out


def _append_missed(engine: str, new: dict[str, str]) -> None:
    if not new:
        return
    with MISS_FILES[engine].open("a", encoding="utf-8") as fh:
        for pid, reason in sorted(new.items(), key=lambda kv: str(kv[0])):
            fh.write(f"{pid} {reason}\n")


def _as_uuid(k: str):
    """台账键是 UUID 字符串；无法解析的条目丢弃（不注入非法过滤值）。"""
    import uuid

    try:
        return uuid.UUID(str(k))
    except (ValueError, TypeError, AttributeError):
        return None


def _select_rows(limit: int, missed: dict[str, str]) -> list:
    from sqlalchemy import case, not_, or_

    with get_session_factory()() as session:
        q = session.query(Poi).filter(
            Poi.status == "active",
            Poi.city.isnot(None),
            Poi.city != "",
            or_(Poi.opening_hours.is_(None), Poi.rating.is_(None)),
        )
        if missed:
            ids = [u for u in (_as_uuid(k) for k in missed) if u is not None]
            if ids:
                q = q.filter(not_(Poi.id.in_(ids)))
        # 既有优先级序列（2026-11-03 用户指令「按既有优先级清单填」）：
        # 与 app/jobs/enrich_ctrip_detail._source_rank 同序——规划器最先
        # 挑出的行（unesco/5a/博物馆系/artmuseum）先吃每日配额。
        rank = case(
            *[
                (Poi.source == src, rank_)
                for rank_, src in enumerate(
                    (
                        "unesco",
                        "5a",
                        "museum1",
                        "museum2",
                        "museum3",
                        "artmuseum",
                        "amap",
                        "chinatravel",
                        "osm",
                    )
                )
            ],
            else_=5,
        )
        rows = (
            q.order_by(rank, Poi.rating.desc().nullslast(), Poi.id)
            .limit(limit)
            .all()
        )
        session.expunge_all()
    return rows


# ---------- baidu 引擎（place v2 scope=2） ----------


async def _run_baidu(limit: int, concurrency: int) -> dict:
    from app.jobs.enrich_baidu_map import (
        _key_from_env,
        _match_name,
        _search,
        _variants,
        _write_row,
    )

    missed = _load_missed("baidu")
    rows = _select_rows(limit, missed)
    stats: dict = {
        "engine": "baidu",
        "selected": len(rows),
        "skipped_miss_file": len(missed),
        "matched": 0,
        "no_match": 0,
        "matched_no_fields": 0,
        "filled": {},
        "quota_stop": None,
        "errors": 0,
    }
    if not rows:
        return stats

    key = _key_from_env()
    if not key:
        stats["quota_stop"] = "no_key"
        return stats

    sem = asyncio.Semaphore(max(1, concurrency))
    new_missed: dict[str, str] = {}

    def _process_one(row: Poi) -> str:
        import httpx as _hx

        name = (row.name_zh or "").strip()
        city = (row.city or "").strip()
        variants = _variants(name)
        with _hx.Client(
            headers={"User-Agent": "chinatrip-enrich/0.1"}, timeout=15
        ) as client:
            hit = None
            for v in variants:
                d = _search(client, key, v, city)
                for cand in d.get("results") or []:
                    if _match_name(cand.get("name", ""), variants):
                        hit = cand
                        break
                if hit:
                    break
        if not hit:
            return "no_match"
        di = hit.get("detail_info") or {}
        has_fields = any(
            isinstance(di.get(k), str) and di.get(k)
            for k in ("shop_hours", "regular_open_hour")
        ) or di.get("overall_rating") not in (None, "")
        written = _write_row(get_session_factory(), row.id, hit)
        if written:
            for col in written:
                stats["filled"][col] = stats["filled"].get(col, 0) + 1
            return "filled"
        return "matched_no_fields" if has_fields else "no_fields"

    async def _guarded(row: Poi) -> None:
        async with sem:
            try:
                outcome = await asyncio.to_thread(_process_one, row)
            except Exception as exc:  # noqa: BLE001 — 配额类见下方 status 分支
                st = getattr(exc, "status", None)
                if st in _QUOTA_STATUSES:
                    stats["quota_stop"] = f"quota:{st}"
                    return
                stats["errors"] += 1
                return
        if outcome == "filled":
            stats["matched"] += 1
        elif outcome == "no_match":
            stats["no_match"] += 1
            new_missed[str(row.id)] = f"baidu no_match（{date.today().isoformat()}）"
        else:
            stats["matched_no_fields"] += 1
            new_missed[str(row.id)] = (
                f"baidu 无目标字段（{date.today().isoformat()}）"
            )

    await asyncio.gather(*(_guarded(r) for r in rows))
    # 台账只含已尝试且确定性失败的行（未尝试行不入 new_missed）——配额
    # 中途停批时也要写入，否则这批 no_match 次日重试白烧配额（2026-11-04
    # 03:55 批实测丢了 22 条）。
    _append_missed("baidu", new_missed)
    stats["new_missed"] = len(new_missed)
    return stats


# ---------- amap 引擎（v5 place/text show_fields=business） ----------


def _write_row_amap(factory, poi_id, out: dict) -> list[str]:
    """逐列只填空；与 enrich_amap_detail 同口径（amap 触点）。"""
    written: list[str] = []
    with factory() as session:
        row = session.get(Poi, poi_id)
        if row is None:
            return written
        if row.opening_hours is None and out.get("opening_hours"):
            row.opening_hours = str(out["opening_hours"]).strip()[:200]
            row.hours_source = "amap"
            written.append("opening_hours")
        if row.rating is None and out.get("rating"):
            try:
                rv = float(out["rating"])
            except (TypeError, ValueError):
                rv = None
            if rv is not None and 0 <= rv <= 5:
                row.rating = rv
                row.rating_source = "amap"
                written.append("rating")
        if row.phone is None and out.get("tel"):
            row.phone = str(out["tel"]).strip()[:50]
            written.append("phone")
        if row.business_area is None and out.get("business_area"):
            row.business_area = str(out["business_area"]).strip()[:50]
            written.append("business_area")
        if row.photos is None and out.get("photos"):
            row.photos = out["photos"]
            written.append("photos")
        if written:
            session.commit()
    return written


async def _run_amap(limit: int, concurrency: int) -> dict:
    from app.config import get_settings
    from app.jobs.enrich_baidu_map import _match_name, _variants
    from app.services.amap_client import (
        AmapClient,
        AmapPunishedError,
        AmapQuotaExhaustedError,
    )

    missed = _load_missed("amap")
    rows = _select_rows(limit, missed)
    stats: dict = {
        "engine": "amap",
        "selected": len(rows),
        "skipped_miss_file": len(missed),
        "matched": 0,
        "no_match": 0,
        "matched_no_fields": 0,
        "filled": {},
        "quota_stop": None,
        "errors": 0,
    }
    if not rows:
        return stats

    settings = get_settings()
    if not settings.amap_api_key:
        stats["quota_stop"] = "no_key"
        return stats

    client = AmapClient(key=settings.amap_api_key, timeout_seconds=10.0)
    sem = asyncio.Semaphore(max(1, concurrency))
    new_missed: dict[str, str] = {}

    async def _process_one(row: Poi) -> str:
        name = (row.name_zh or "").strip()
        city = (row.city or "").strip()
        variants = _variants(name)
        # 坐标→location：text 配额尽时 search_hours 自动降级 v5 /place/around
        # （独立配额池，3km 内首条）；坐标缺失则无降级（各行单次 text 查询）。
        location = row.location
        loc_str = None
        if location is not None:
            try:
                from geoalchemy2.shape import to_shape

                pt = to_shape(location)
                loc_str = f"{pt.x:.6f},{pt.y:.6f}"
            except Exception:  # noqa: BLE001 — 坐标解析失败不影响主链
                loc_str = None
        out: dict | None = None
        for v in variants:
            out = await client.search_hours(v, city=city, location=loc_str)
            if out and (out.get("opening_hours") or out.get("rating")):
                break
        matched = (out or {}).get("matched") or ""
        if not matched or not _match_name(matched, variants):
            return "no_match"
        written = await asyncio.to_thread(
            _write_row_amap, get_session_factory(), row.id, out
        )
        if written:
            for col in written:
                stats["filled"][col] = stats["filled"].get(col, 0) + 1
            return "filled"
        return "matched_no_fields"

    async def _guarded(row: Poi) -> None:
        async with sem:
            try:
                outcome = await _process_one(row)
            except AmapQuotaExhaustedError:
                stats["quota_stop"] = "quota"
                return
            except AmapPunishedError:
                stats["quota_stop"] = "waf"
                return
            except Exception:  # noqa: BLE001 — 单行失败只计数
                stats["errors"] += 1
                return
        if outcome == "filled":
            stats["matched"] += 1
        elif outcome == "no_match":
            stats["no_match"] += 1
            new_missed[str(row.id)] = f"amap no_match（{date.today().isoformat()}）"
        else:
            stats["matched_no_fields"] += 1
            new_missed[str(row.id)] = (
                f"amap 无目标字段（{date.today().isoformat()}）"
            )

    await asyncio.gather(*(_guarded(r) for r in rows))
    # 同 baidu：台账只含已尝试的确定性失败行，配额/WAF 停批也照写。
    _append_missed("amap", new_missed)
    stats["new_missed"] = len(new_missed)
    return stats


async def run(limit: int, concurrency: int, engine: str) -> dict:
    if engine == "amap":
        return await _run_amap(limit, concurrency)
    return await _run_baidu(limit, concurrency)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=("baidu", "amap"), default="baidu")
    parser.add_argument("--limit", type=int, default=120)
    parser.add_argument("--concurrency", type=int, default=2)
    args = parser.parse_args()
    stats = asyncio.run(run(args.limit, args.concurrency, args.engine))
    print(json.dumps(stats, ensure_ascii=False))
    sys.exit(2 if stats.get("quota_stop") else 0)


if __name__ == "__main__":
    main()
