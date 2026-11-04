# -*- coding: utf-8 -*-
"""按景区/预约名录回填 museum1/2/3 的 `city`（2026-11-03 数据债收口）.

背景：博物馆批次导入时 `city` 列缺失，回退写成了省名（`山东`/`陕西`/…），
规划池按精确城市名取点，这些行整批取不到。

证据来源（`DESIGN/POIS DATASOURCE`，均带 province + city）：

    13_4A级旅游景区_官方汇编4674.csv    景区名往往是「地名 + 馆名 + 景区」
    09_热门预约景点_门票预定.csv         热门预约点
    15_国家二级博物馆_七省补缺.csv       七省二级馆补缺

匹配两条通道，都要求自洽：

1. **同名**（剥括号/尾部「景区」后相等）→ 直接取名录 city（名录 city 必须
   与库内旧值同省，旧值本身就是省名口径）；
2. **包含**（一方是另一方的前/后缀）→ 用**名录全名**在**旧省**语境下解析
   出的城市必须等于名录 city，否则丢弃（`钟鼓楼` 属于北京名录，但库内是
   `西安市钟鼓楼博物馆`，解析出西安≠北京 → 拒绝）。

只写到 `known_cities()` 内、且不是省名本身的城市；逐行 commit。

用法：
    .venv\\Scripts\\python.exe ops\\backfill_museum_city_from_scenic_csv.py
    .venv\\Scripts\\python.exe ops\\backfill_museum_city_from_scenic_csv.py --apply
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_CSV_ROOT = Path(r"D:\CHINATRIP\DESIGN\POIS DATASOURCE")
CSV_FILES = (
    "13_4A级旅游景区_官方汇编4674.csv",
    "09_热门预约景点_门票预定.csv",
    "15_国家二级博物馆_七省补缺.csv",
)
SOURCES = ("museum1", "museum2", "museum3")

_PARENS = re.compile(r"[（(].*?[)）]")
_TAIL = re.compile(r"(景区|景点|旅游区|游览区)$")


def norm_name(name: str) -> str:
    s = _PARENS.sub("", (name or "").strip())
    s = re.sub(r"\s+", "", s)
    return _TAIL.sub("", s)


def load_evidence(root: Path) -> list[tuple[str, str, str, str]]:
    """[(province, city_raw, name_zh, csv 文件名)]."""
    out: list[tuple[str, str, str, str]] = []
    for fname in CSV_FILES:
        path = root / fname
        if not path.exists():
            print(f"缺文件，跳过: {path}")
            continue
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                name = (row.get("name_zh") or "").strip()
                city_raw = (row.get("city") or "").strip()
                prov = (row.get("province") or "").strip()
                city = (row.get("city(名单口径)") or "").strip()
                city_raw = city_raw or city
                if name and city_raw and prov:
                    out.append((prov, city_raw, name, fname))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="写库；缺省只打印")
    ap.add_argument("--csv-root", default=str(DEFAULT_CSV_ROOT))
    args = ap.parse_args()

    from app.services.poi_city import (
        _city_province,
        _province_of,
        _province_short,
        canonical_city,
        known_cities,
        resolve_city,
    )

    kc = known_cities()
    city_prov = _city_province()
    provinces = set(city_prov.values())

    def as_province(value: str) -> str | None:
        v = _province_short(value or "")
        return v if v in provinces else None

    def as_city(province: str, city_raw: str) -> str | None:
        cand = resolve_city(province, city_raw) or canonical_city(city_raw)
        if not cand or cand not in kc or cand in provinces:
            return None
        if city_prov.get(cand) != as_province(province):
            return None
        return cand

    evidence = load_evidence(Path(args.csv_root))
    print(f"名录行={len(evidence)}")

    from app.db import get_session_factory
    from app.models import Poi

    fac = get_session_factory()
    with fac() as session:
        rows = (
            session.query(Poi).filter(Poi.source.in_(SOURCES)).all()
        )
    plan: list[tuple[int, str, str, str, str]] = []
    unresolved = [
        (r.city or "", r.name_zh or "")
        for r in rows
        if (r.city or "") not in kc and not as_province(r.city or "")
    ]
    for r in rows:
        old = (r.city or "").strip()
        if old in kc:
            continue
        stored_prov = as_province(old) or city_prov.get(old)
        if not stored_prov:
            continue
        db_norm = norm_name(r.name_zh or "")
        if len(db_norm) < 4:
            continue
        best: tuple[int, str, str] | None = None  # (rank, new, csv_name)
        for prov, city_raw, csv_name, _fname in evidence:
            if as_province(prov) != stored_prov:
                continue
            new = as_city(prov, city_raw)
            if not new or new == old:
                continue
            csv_norm = norm_name(csv_name)
            if len(csv_norm) < 4:
                continue
            if csv_norm == db_norm:
                rank = 0
            elif db_norm.endswith(csv_norm) or csv_norm.endswith(db_norm):
                # 含地名前缀的名录全名必须自洽解析成同一城市
                if resolve_city(stored_prov, csv_name) != new:
                    continue
                rank = 1
            else:
                continue
            if best is None or rank < best[0]:
                best = (rank, new, csv_name)
        if best:
            plan.append((r.id, old, best[1], r.name_zh or "", best[2]))

    print(
        f"库内行={len(rows)} "
        # 直辖市名同时是省名与 canonical 城市名（北京/上海/天津/重庆），
        # 统计「省名兜底伪值」时必须排除，否则 1300 行博物馆会虚报 311 而非 195
        f"省名回退行={sum(1 for r in rows if (r.city or '') in provinces and (r.city or '') not in kc)}"
    )
    print(f"可回填={len(plan)} 未解析={len(unresolved) - len(plan)}")
    for _id, old, new, name, csv_name in plan:
        print(f"    {old} -> {new} | {name}  <= {csv_name}")
    if not plan:
        print("no hits (empty plan)")
        return 0
    if not args.apply:
        print("dry-run only — rerun with --apply to write")
        return 0

    fixed = 0
    for pid, _old, new, _name, _csv in plan:
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
