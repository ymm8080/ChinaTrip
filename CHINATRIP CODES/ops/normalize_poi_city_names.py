# -*- coding: utf-8 -*-
"""normalize_poi_city_names.py — 州/地级市名归一（backlog P1 #5）.

背景：regeo 回填历史行产出「阿坝藏族羌族自治州 / 红河哈尼族彝族自治州 /
伊犁州 / 阿克苏地区」等全名或带州后缀名，与 `weather.CITY_ADCODES`
（=`plan.KNOWN_CITIES`）注册短名口径不一致，按城查池会 miss。

规则：对不在 KNOWN_CITIES 的 `pois.city` 值跑 `poi_city.canonical_city`；
仅当归一结果落在 `poi_city.known_cities()`（canonical 名域）内且与原值
不同才改。不碰空串（长白山等空 city 由 fill_all_missing_cities.py 另管）。

批量 UPDATE 逐条 commit（backlog 已知坑：攒批炸全回滚还打印假成功）。

用法（在 `CHINATRIP CODES` 下）：
    .venv\\Scripts\\python.exe ops\\normalize_poi_city_names.py            # dry-run
    .venv\\Scripts\\python.exe ops\\normalize_poi_city_names.py --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="写库；缺省只打印")
    ap.add_argument(
        "--tables",
        default="pois",
        help="逗号分隔：pois / pois,restaurants / restaurants",
    )
    args = ap.parse_args()

    from sqlalchemy import text

    from app.db import get_session_factory
    from app.services.agent.plan import KNOWN_CITIES
    from app.services.poi_city import canonical_city, city_from_name, known_cities

    known = frozenset(KNOWN_CITIES)
    canonical_domain = known_cities()
    fac = get_session_factory()
    for table in [t.strip() for t in args.tables.split(",") if t.strip()]:
        with fac() as session:
            rows = session.execute(
                text(f"SELECT city, count(*) FROM {table} GROUP BY city")
            ).fetchall()
        mapping: dict[str, str] = {}
        skip_foreign: dict[str, str] = {}
        for city, n in rows:
            c = (city or "").strip()
            if not c or c in known:
                continue
            canon = canonical_city(c)
            if canon in canonical_domain and canon != c:
                mapping[c] = canon
            elif canon != c:
                skip_foreign[c] = canon
        print(f"{table}: base_rows={sum(n for _, n in rows)}")
        counts = dict(rows)
        total = sum(counts[old] for old in mapping) if mapping else 0
        for old, new in sorted(mapping.items(), key=lambda kv: -counts[kv[0]]):
            print(f"    {old!r} -> {new!r} : {counts[old]}")
        if mapping:
            print(f"    -> {len(mapping)} mappings, {total} rows to update")
        if skip_foreign:
            print(f"    (unchanged, not canonical): {len(skip_foreign)}")
            for old, new in sorted(skip_foreign.items()):
                print(f"    skip {old!r} -> {new!r} : {counts[old]}")

        # 第二遍：historical 值仍不属于 canonical 域（区县级 / 脏串），按
        # 行解析——address（含省前缀）→ district → city 本身 → 名称显式
        # 前缀（`宁波市天一阁博物院`）；仅当结果落 canonical 域才改
        # （逐行 UPDATE + 逐行 commit）。
        from app.services.poi_city import _city_province, resolve_city

        city_province = _city_province()
        province_names = set(city_province.values())

        if canonical_domain:
            with fac() as session:
                pending = session.execute(
                    text(
                        f"SELECT id, city, address, district, name_zh FROM {table} "
                        "WHERE city IS NOT NULL AND city <> ''"
                    )
                ).fetchall()
            legacy = [
                (pid, c, addr or "", district or "", name or "")
                for pid, c, addr, district, name in pending
                if c not in canonical_domain and c not in mapping
            ]
            print(f"    second-pass legacy rows: {len(legacy)}")
            plan: list[tuple[int, str, str, str]] = []
            for pid, c, addr, district, name in legacy:
                # 跨市脏串（'临汾市、延安'）只取首段解析——best effort，逐行落库
                dirty = any(ch in c for ch in "、；;，")
                cand = c.split("、")[0].strip() if dirty else c
                if cand in province_names:
                    # 省名当 city 的存量行（导入期 city 列缺失的兜底伪值）：
                    # 该值只能当**省级语境**用，绝不能让 `resolve_city(None, c)`
                    # 把省名原样返回、从而短路掉名称解析（那是 515 行残留的成因）。
                    new = city_from_name(name, cand)
                    if not new:
                        for ev in (district, addr):
                            got = resolve_city(None, ev) if ev else None
                            if got and city_province.get(got) == cand:
                                new = got
                                break
                else:
                    new = (
                        resolve_city(None, addr)
                        or resolve_city(None, district)
                        or resolve_city(None, cand)
                        or city_from_name(name, cand)
                    )
                if not new or new not in canonical_domain or new == c:
                    continue
                # 省语境下必须自洽（名称里的地名确实属于该省）；无省语境
                # 的区县/脏串路径不做额外约束
                if cand in province_names and city_province.get(new) != cand:
                    continue
                plan.append((pid, c, new, name))
            print(f"    second-pass planned rows: {len(plan)}")
            for _pid, old, new, name in plan[:40]:
                print(f"      {old!r} -> {new!r} : {name}")
            if len(plan) > 40:
                print(f"      … 其余 {len(plan) - 40} 行同类")
            fixed = 0
            if args.apply:
                for pid, _old, new, _name in plan:
                    with fac() as session:
                        session.execute(
                            text(f"UPDATE {table} SET city = :new WHERE id = :pid"),
                            {"new": new, "pid": pid},
                        )
                        session.commit()
                    fixed += 1
                print(f"    second-pass applied rows: {fixed}")

        if not args.apply or not mapping:
            continue
        for old, new in sorted(mapping.items()):
            expect = dict(rows)[old]
            with fac() as session:
                res = session.execute(
                    text(f"UPDATE {table} SET city = :new WHERE city = :old"),
                    {"new": new, "old": old},
                )
                session.commit()
                if res.rowcount != expect:
                    print(f"    !! {old!r}: updated {res.rowcount} != {expect}")
            print(f"    applied {old!r} -> {new!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
