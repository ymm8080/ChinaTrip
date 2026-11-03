# -*- coding: utf-8 -*-
"""按权威名录 CSV 的 province/locality 回填 `pois.city`（2026-11-03）.

背景：museum1/2/3 + histown/street 批次把区县级或省名写进了 `city`
（`宝山区` / `海城` / `永定区` / `江北区` …），而 `top_pois_in_city` 是
精确城市名匹配——这些行在规划池里永远取不到。原始名录
`DESIGN/POIS DATASOURCE/*.csv` 自带 `province` + `locality`（或 `city`）
两列，是最可靠的行政归属证据，本作业据此回填。

作业表（source → 文件名 + 属地列）：

    histown → 05_中国历史文化名镇_312.csv        province + locality
    street  → 01_国家级旅游休闲街区_全四批204.csv  province + city

解析顺序：`resolve_city(province, locality)` → `city_from_name(name,province)`
→ `canonical_city(locality)`；结果必须落在 `known_cities()`（canonical 域）
且与原 `city` 不同才写。逐行 UPDATE + 逐行 commit（backlog 既有坑：攒批
UPDATE 一炸全回滚还打印假成功）。

幂等可重跑：再跑一遍 plan 为空即 done。

用法（在 `CHINATRIP CODES` 下）：
    .venv\\Scripts\\python.exe ops\\backfill_city_from_datasource_csv.py
    .venv\\Scripts\\python.exe ops\\backfill_city_from_datasource_csv.py --apply
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_CSV_ROOT = Path(r"D:\CHINATRIP\DESIGN\POIS DATASOURCE")

# source -> (csv 文件名, 归属地名列候选)
JOBS: dict[str, tuple[str, tuple[str, ...]]] = {
    "histown": ("05_中国历史文化名镇_312.csv", ("locality", "city")),
    "street": ("01_国家级旅游休闲街区_全四批204.csv", ("city", "locality")),
}


def load_csv_rows(path: Path, place_cols: tuple[str, ...]) -> dict[str, tuple[str, str]]:
    """name_zh -> (province, 属地原文)；同名冲突取首个（名录内本就唯一）."""
    out: dict[str, tuple[str, str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            name = (row.get("name_zh") or "").strip()
            province = (row.get("province") or "").strip()
            place = ""
            for col in place_cols:
                place = (row.get(col) or "").strip()
                if place:
                    break
            if name and province:
                out.setdefault(name, (province, place))
    return out


def resolve_place(name: str, province: str, place: str) -> str | None:
    from app.services.poi_city import canonical_city, city_from_name, known_cities
    from app.services.poi_city import resolve_city

    kc = known_cities()
    for cand in (
        resolve_city(province, place) if place else None,
        resolve_city(province, name),
        city_from_name(name, province),
        canonical_city(place) if place else None,
    ):
        if cand and cand in kc:
            return cand
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="写库；缺省只打印")
    ap.add_argument(
        "--only",
        default="",
        help="逗号分隔的 source 子集（histown,street）；缺省全跑",
    )
    ap.add_argument("--csv-root", default=str(DEFAULT_CSV_ROOT))
    args = ap.parse_args()

    wanted = [s.strip() for s in args.only.split(",") if s.strip()] or list(JOBS)
    csv_root = Path(args.csv_root)

    from app.db import get_session_factory
    from app.models import Poi

    fac = get_session_factory()
    total_plan: list[tuple[int, str, str, str, str]] = []
    for source in wanted:
        fname, place_cols = JOBS[source]
        path = csv_root / fname
        if not path.exists():
            print(f"[{source}] 缺文件，跳过: {path}")
            continue
        evidence = load_csv_rows(path, place_cols)
        with fac() as session:
            rows = session.query(Poi).filter(Poi.source == source).all()
        matched = [r for r in rows if (r.name_zh or "") in evidence]
        plan: list[tuple[int, str, str, str, str]] = []
        unresolved: list[tuple[str, str, str]] = []
        for r in matched:
            province, place = evidence[r.name_zh]
            new = resolve_place(r.name_zh or "", province, place)
            old = r.city or ""
            if not new or new == old:
                if not new:
                    unresolved.append((old, r.name_zh or "", province))
                continue
            plan.append((r.id, old, new, r.name_zh or "", province))
        print(
            f"[{source}] csv={len(evidence)} 库内行={len(rows)} 匹配={len(matched)} "
            f"待修={len(plan)} 未解析={len(unresolved)}"
        )
        for _id, old, new, name, province in plan[:20]:
            print(f"    {old!r} -> {new!r} | {province} {name}")
        if len(plan) > 20:
            print(f"    … 其余 {len(plan) - 20} 行同类")
        for old, name, province in unresolved[:10]:
            print(f"    未解析 [{province}] {old!r} {name}")
        total_plan.extend(plan)

    print(f"合计待修 {len(total_plan)} 行")
    if not total_plan:
        print("no hits (empty plan)")
        return 0
    if not args.apply:
        print("dry-run only — rerun with --apply to write")
        return 0

    fixed = 0
    for pid, _old, new, _name, _prov in total_plan:
        with fac() as session:
            poi = session.get(Poi, pid)
            if poi is None:
                continue
            poi.city = new
            session.commit()
        fixed += 1
    print(f"applied {fixed} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
