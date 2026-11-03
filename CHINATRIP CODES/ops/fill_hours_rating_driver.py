"""营业时间/评分日批驱动（ops）：百度地点检索逐行收割，miss 台账防重烧。

背景（2026-11-03 用户拍板「选对源、填到全完成」）：美团/点评无开放数据
API；携程详情页 PoC 目录前 200 页对长尾行命中率 ~3%（今日已榨干）；
amap v5 detail 对本库 97% 行无 business 块。百度 place v2 scope=2 的
overall_rating/shop_hours 是长尾行唯一可规模化收割的确定性源，但个人
档 ~100 次/日——故按 backfill_coords_driver 模式包装：

- 目标行：active + 有 city + hours 或 rating 为空（enrich_baidu_map
  的 select_targets 口径），剔除台账内行；
- 台账 ops/fill_hours_rating_missed.txt（`poi_id 原因`）：no_match /
  matched 无目标字段 / 空响应均属确定性失败，记账后不再重试——配额
  永远花在新行上，全库试完一轮即「完成」；
- 配额错误（status 401/402/302）首撞即停，未尝试行不入台账，次日配额
  重置后续跑（fill-empty-only，无损）；
- 每行最多 3 个名称变体 × 1 次 region 检索。

用法：python ops/fill_hours_rating_driver.py [--limit 120] [--concurrency 2]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import get_session_factory  # noqa: E402
from app.models import Poi  # noqa: E402

MISS_FILE = Path(__file__).resolve().parent / "fill_hours_rating_missed.txt"

_QUOTA_STATUSES = {401, 402, 302}


def _load_missed() -> dict[str, str]:
    if not MISS_FILE.exists():
        return {}
    out: dict[str, str] = {}
    for line in MISS_FILE.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split(None, 1)
        if parts:
            out[parts[0]] = parts[1] if len(parts) > 1 else ""
    return out


def _append_missed(new: dict[str, str]) -> None:
    if not new:
        return
    with MISS_FILE.open("a", encoding="utf-8") as fh:
        for pid, reason in sorted(new.items(), key=lambda kv: str(kv[0])):
            fh.write(f"{pid} {reason}\n")


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
            q = q.filter(not_(Poi.id.in_([_as_int(k) for k in missed])))
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
            q.order_by(rank, Poi.rating.desc().nullslast(), Poi.id).limit(limit).all()
        )
        session.expunge_all()
    return rows


def _as_int(k: str):
    try:
        return int(k)
    except ValueError:
        return -1


async def run(limit: int, concurrency: int) -> dict:

    from app.jobs.enrich_baidu_map import (
        _QUOTA_STATUSES as _Q,  # noqa: F401 — 语义对齐引用
    )
    from app.jobs.enrich_baidu_map import (
        _key_from_env,
        _match_name,
        _search,
        _variants,
        _write_row,
    )

    assert _Q == _QUOTA_STATUSES
    missed = _load_missed()
    rows = _select_rows(limit, missed)
    stats: dict = {
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
        """返回 'filled' | 'no_match' | 'matched_no_fields'；配额错误抛出。"""
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
            except Exception as exc:
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
            new_missed[str(row.id)] = f"baidu 无目标字段（{date.today().isoformat()}）"

    await asyncio.gather(*(_guarded(r) for r in rows))
    if not stats["quota_stop"]:
        _append_missed(new_missed)
    stats["new_missed"] = len(new_missed)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=120)
    parser.add_argument("--concurrency", type=int, default=2)
    args = parser.parse_args()
    stats = asyncio.run(run(args.limit, args.concurrency))
    import json

    print(json.dumps(stats, ensure_ascii=False))
    sys.exit(2 if stats.get("quota_stop") else 0)


if __name__ == "__main__":
    main()
