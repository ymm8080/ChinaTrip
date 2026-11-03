# -*- coding: utf-8 -*-
"""4A 批次深度质检（2026-11-03 立项，用户批准）：逐行高德回源核验。

三维比对（只读，不写库）：
  1. 存在性：高德关键词搜索（city 限定 citylimit）是否有命中；
  2. 名称：命中 top1 与 name_zh 归一后 精确/互含/不符；
  3. 坐标：haversine(DB location, 高德 top1)——<300m 正常 / 300–2000m
     漂移 / >2000m 远离 / 库内无坐标跳过。

产出：ops/qc_4a_amap_report_2026-11-03.md + ops/qc_4a_amap_suspects.csv
（可疑行含高德 top1 名称/坐标，供人工复核）。
配额耗尽（AmapQuotaExhaustedError）优雅中止并落部分结果。
用法：python ops/qc_4a_amap_check.py [--limit N] [--concurrency 2]
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from geoalchemy2.shape import to_shape

from app.config import get_settings
from app.db import get_session_factory
from app.models import Poi
from app.services.amap_client import AmapClient, AmapQuotaExhaustedError
from app.services.coords import haversine_m
from app.services.map_provider import build_vendor

OUT_MD = Path(__file__).parent / "qc_4a_amap_report_2026-11-03.md"
OUT_CSV = Path(__file__).parent / "qc_4a_amap_suspects.csv"

_OK_DIST_M = 300.0
_FAR_DIST_M = 2000.0


def _norm_name(s: str | None) -> str:
    if not s:
        return ""
    s = re.sub(r"[（(].*?[)）]", "", s)
    s = re.sub(r"[\s\-—–·、，,（）()]", "", s)
    return s.strip()


def _name_rel(db_name: str, hit_name: str) -> str:
    a, b = _norm_name(db_name), _norm_name(hit_name)
    if not a or not b:
        return "empty"
    if a == b:
        return "exact"
    if a in b or b in a:
        return "contains"
    return "differs"


def _db_lonlat(geom) -> tuple[float, float] | None:
    if geom is None:
        return None
    try:
        p = to_shape(geom)
        return (p.x, p.y)
    except Exception:
        return None


async def qc_row(
    client: AmapClient,
    sem: asyncio.Semaphore,
    row_id,
    city: str,
    name: str,
    lonlat: tuple[float, float] | None,
    stats: dict,
    suspects: list[dict],
) -> None:
    async with sem:
        try:
            hits = await client.search_poi(name, city=city or None)
        except AmapQuotaExhaustedError:
            stats["quota_aborted"] += 1
            raise
        except Exception as exc:
            stats["errors"] += 1
            stats.setdefault("error_detail", []).append(
                {"name": name, "err": type(exc).__name__}
            )
            return
        if not hits:
            stats["not_found"] += 1
            suspects.append(
                {
                    "bucket": "not_found",
                    "city": city,
                    "name_zh": name,
                    "amap_name": "",
                    "dist_m": "",
                }
            )
            return
        top = hits[0]
        rel = _name_rel(name, top.get("name") or "")
        hloc = top.get("location") or {}
        dist = None
        if lonlat and isinstance(hloc, dict):
            hlon, hlat = hloc.get("lon"), hloc.get("lat")
            if hlon is not None and hlat is not None:
                try:
                    dist = haversine_m(lonlat[0], lonlat[1], float(hlon), float(hlat))
                except Exception:
                    dist = None
        bucket = "matched"
        if rel == "differs":
            bucket = "name_suspect"
        if dist is not None:
            if dist > _FAR_DIST_M:
                bucket = "coord_far"
            elif dist > _OK_DIST_M and bucket == "matched":
                bucket = "coord_drift"
        stats[bucket] += 1
        if dist is not None:
            stats["dist_samples"].append(dist)
        if bucket != "matched":
            suspects.append(
                {
                    "bucket": bucket,
                    "city": city,
                    "name_zh": name,
                    "amap_name": top.get("name") or "",
                    "dist_m": int(dist) if dist is not None else "",
                }
            )


async def run(factory, client, *, limit: int, concurrency: int) -> dict:
    with factory() as session:
        rows = (
            session.query(Poi).filter(Poi.source == "4a", Poi.status == "active").all()
        )
    targets = [
        (r.id, r.city or "", r.name_zh or "", _db_lonlat(r.location))
        for r in rows
        if (r.name_zh or "").strip()
    ]
    if limit > 0:
        targets = targets[:limit]
    stats: dict = {
        "targets": len(targets),
        "matched": 0,
        "name_suspect": 0,
        "coord_drift": 0,
        "coord_far": 0,
        "not_found": 0,
        "errors": 0,
        "quota_aborted": 0,
        "dist_samples": [],
    }
    suspects: list[dict] = []
    sem = asyncio.Semaphore(max(1, concurrency))
    try:
        await asyncio.gather(
            *(qc_row(client, sem, *t, stats, suspects) for t in targets)
        )
    except AmapQuotaExhaustedError:
        pass  # 配额中止：部分结果已收集
    return stats, suspects


def write_reports(stats: dict, suspects: list[dict]) -> None:
    d = stats.get("dist_samples") or []
    with io.open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["bucket", "city", "name_zh", "amap_top1_name", "dist_m"])
        for s in suspects:
            w.writerow(
                [s["bucket"], s["city"], s["name_zh"], s["amap_name"], s["dist_m"]]
            )
    with io.open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("# 4A 批次高德回源深度质检（2026-11-03）\n\n")
        f.write(
            f"> 口径：高德 place/text 关键词搜索（city 限定），"
            f"top1 命中比对名称与坐标。"
            f"目标 {stats['targets']} 行；配额中止标记={stats['quota_aborted']}。\n\n"
            "| 桶 | 行数 | 含义 |\n|---|---|---|\n"
            f"| matched | {stats['matched']} | 名称精确/互含且坐标 <300m |\n"
            f"| name_suspect | {stats['name_suspect']} | top1 名称与库内名不互含 |\n"
            f"| coord_drift | {stats['coord_drift']} | 名称可但坐标漂移 300–2000m |\n"
            f"| coord_far | {stats['coord_far']} | 坐标相距 >2000m（优先复核） |\n"
            f"| not_found | {stats['not_found']} | 高德查无此名（可能上游名单噪声） |\n"
            f"| errors | {stats['errors']} | 网络/接口异常 |\n\n"
        )
        if d:
            f.write(
                f"坐标距离分布：中位 {statistics.median(d):.0f}m / "
                f"p90 {sorted(d)[int(len(d) * 0.9)]:.0f}m / "
                f"max {max(d):.0f}m（n={len(d)}）\n\n"
            )
        f.write(f"可疑明细见 qc_4a_amap_suspects.csv（{len(suspects)} 行）。\n")
    print(f"report: {OUT_MD}\ncsv: {OUT_CSV}")


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="4A 批次回源深度质检")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument(
        "--vendor",
        default="baidu",
        choices=("baidu", "amap", "tencent"),
        help="真值源（默认 baidu：2026-11-03 实测 amap key 被阿里云 WAF 风控、"
        "tencent 日配额尽，baidu 正常且坐标归一 GCJ-02）",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    client = build_vendor(args.vendor, settings)
    if client is None:
        print(
            json.dumps(
                {"error": f"vendor key not configured: {args.vendor}"},
                ensure_ascii=True,
            )
        )
        return 1
    factory = get_session_factory()
    stats, suspects = asyncio.run(
        run(factory, client, limit=args.limit, concurrency=args.concurrency)
    )
    write_reports(stats, suspects)
    print(
        json.dumps(
            {k: v for k, v in stats.items() if k != "dist_samples"}, ensure_ascii=True
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
