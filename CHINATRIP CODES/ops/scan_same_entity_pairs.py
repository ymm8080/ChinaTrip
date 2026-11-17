# -*- coding: utf-8 -*-
"""同实体重复行扫描与退役执行器（秦始皇陵/兵马俑 DEDUP 类根修）。

模式：
  scan        严格三类对台账：S1同名 / S2同核(剥尾词) / S3互含。只列不删。
  apply-s1    机械退役 S1 同名跨源重复行：keeper=源优先级最高（同分比评分/
              坐标），keeper 空字段从败者回填（全源优先级铁律）、别名并入，
              itinerary/trip 引用 poi_id 重指向 keeper，败者 status='retired'。
  apply-group <keeper_id> <loser_id...>
              手工判定的同实体组退役（子序列变体如 秦始皇陵⊂秦始皇帝陵
              不被 S1-S3 覆盖，按用户拍板点名执行），回填/别名/重指向同上。
  apply-s2 <拍板文件>
              S2 同核（剥尾词相等）逐组退役：拍板文件每行 `城市|keeper名`，
              同城同核组内未点名的只列 MISSING 不删，保证逐组人工过目。
  s3-detail    S3 互含对逐对打详情（坐标距离 haversine + 地址 + tags），
              供按用户裁定（以地址判同实体）逐对拍板。
  apply-s3 <拍板文件>
              S3 互含对按三元组拍板退役：每行 `城市|keeper名|败者名`，
              星型拓扑（同实体所有败者指向同一 keeper），找不到行则 SKIP。

判定复用 poi_alternatives 同体闸的剥尾规则；台账输出 utf-8。
"""

from __future__ import annotations

import io
import os
import sys
import uuid
from collections import defaultdict
from math import asin, cos, radians, sin, sqrt

from geoalchemy2 import Geometry
from sqlalchemy import func

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import get_session_factory  # noqa: E402
from app.models import ItineraryItem, Poi, TripItem  # noqa: E402
from app.services.poi_alternatives import _name_core  # noqa: E402
from app.services.poi_details import _name_overlap  # noqa: E402

_SOURCE_PRIORITY = (
    "unesco",
    "5a",
    "museum1",
    "museum2",
    "museum3",
    "artmuseum",
    "street",
    "histown",
    "amap",
    "chinatravel",
    "osm",
)

# keeper 空字段回填清单（仅 keeper 值为空才写，绝不覆盖）
_FILL_FIELDS = (
    "name_en",
    "address",
    "opening_hours",
    "hours_source",
    "phone",
    "website",
    "rating",
    "rating_source",
    "rating_count",
    "suggested_duration_min",
    "duration_source",
    "reservation_required",
    "reservation_advance_days",
    "booking_url",
    "ticket_price_min",
    "ticket_price_max",
    "ticket_source",
    "intro",
    "intro_en",
    "location",
)


def _prio(src: str | None) -> int:
    try:
        return _SOURCE_PRIORITY.index(src or "")
    except ValueError:
        return len(_SOURCE_PRIORITY)


def _keeper_key(r: Poi) -> tuple:
    return (
        _prio(r.source),
        1 if r.rating is None else 0,
        -(r.rating or 0.0),
        0 if r.location is not None else 1,
        str(r.id),
    )


def _load_active(factory) -> list[Poi]:
    with factory() as s:
        return s.query(Poi).filter(Poi.status == "active").all()


def _dist_m(p1, p2) -> int | None:
    if not p1 or not p2 or None in p1 or None in p2:
        return None
    lon1, lat1 = radians(p1[0]), radians(p1[1])
    lon2, lat2 = radians(p2[0]), radians(p2[1])
    a = (
        sin((lat2 - lat1) / 2) ** 2
        + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    )
    return int(6371000 * 2 * asin(sqrt(a)))


def _find_active(factory, city_norm: str, name: str) -> Poi | None:
    with factory() as s:
        hits = [
            r
            for r in s.query(Poi)
            .filter(Poi.status == "active", Poi.name_zh == name)
            .all()
            if (r.city or "").strip().removesuffix("市") == city_norm
        ]
    return hits[0] if len(hits) == 1 else None


def _s1_groups(rows: list[Poi]) -> dict[tuple[str, str], list[Poi]]:
    by_name: dict[tuple[str, str], list[Poi]] = defaultdict(list)
    for r in rows:
        by_name[((r.city or "").strip().removesuffix("市"), r.name_zh)].append(r)
    return {k: v for k, v in by_name.items() if len(v) > 1}


def _repoint_refs(factory, keeper_id, loser_id) -> tuple[int, int]:
    with factory() as s:
        n1 = (
            s.query(ItineraryItem)
            .filter(ItineraryItem.poi_id == loser_id)
            .update({"poi_id": keeper_id}, synchronize_session=False)
        )
        n2 = (
            s.query(TripItem)
            .filter(TripItem.poi_id == loser_id)
            .update({"poi_id": keeper_id}, synchronize_session=False)
        )
        s.commit()
    return n1, n2


def _merge_and_retire(factory, keeper: Poi, loser: Poi, tag: str) -> list[str]:
    ops: list[str] = []
    with factory() as s:
        k = s.get(Poi, keeper.id)
        loser_row = s.get(Poi, loser.id)
        # 1) 引用重指向
        n1, n2 = _repoint_refs(factory, keeper.id, loser.id)
        if n1 or n2:
            ops.append(f"    refs repointed: itinerary={n1} trip={n2}")
        # 2) keeper 空字段回填
        for f in _FILL_FIELDS:
            if getattr(k, f) is None and getattr(loser_row, f) is not None:
                setattr(k, f, getattr(loser_row, f))
                ops.append(f"    fill {f} <- [{loser_row.source}]")
        # 3) tags 并集合并（intl/4a/unesco 等实体级标不随退役丢失）
        added_tags = [t for t in (loser_row.tags or []) if t not in (k.tags or [])]
        if added_tags:
            k.tags = list(k.tags or []) + added_tags
            ops.append(f"    tags union <- [{loser_row.source}] {added_tags}")
        # 4) 别名并入
        aliases = list(k.name_aliases or [])
        new = {loser_row.name_zh, *(a for a in (loser_row.name_aliases or []) if a)}
        added = [a for a in sorted(new) if a not in aliases and a != k.name_zh]
        if added:
            aliases.extend(added)
            k.name_aliases = aliases
            ops.append(f"    aliases += {added}")
        # 5) 退役
        loser_row.status = "retired"
        s.commit()
    ops.append(
        f"    retired [{loser_row.source}] {loser_row.name_zh} "
        f"id={str(loser_row.id)[:8]} ({tag})"
    )
    return ops


def _print_pair(a: Poi, b: Poi, kind: str) -> None:
    hi = sorted([a, b], key=_keeper_key)[0]
    lo = b if hi is a else a
    print(
        f"[{hi.city}|{kind}] keeper=[{hi.source}] {hi.name_zh}  "
        f"(loser [{lo.source}] {lo.name_zh})"
    )


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "scan"
    factory = get_session_factory()

    if mode == "scan":
        rows = _load_active(factory)
        by_city: dict[str, list[Poi]] = defaultdict(list)
        for r in rows:
            by_city[(r.city or "").strip().removesuffix("市")].append(r)
        counts = defaultdict(int)
        for city, items in sorted(by_city.items()):
            for i, a in enumerate(items):
                for b in items[i + 1 :]:
                    if a.name_zh == b.name_zh:
                        _print_pair(a, b, "S1同名")
                        counts["S1"] += 1
                    elif _name_core(a.name_zh) and (
                        _name_core(a.name_zh) == _name_core(b.name_zh)
                    ):
                        _print_pair(a, b, "S2同核")
                        counts["S2"] += 1
                    elif _name_overlap(a.name_zh, b.name_zh):
                        _print_pair(a, b, "S3互含")
                        counts["S3"] += 1
        print(
            f"\nactive={len(rows)}  "
            f"S1={counts['S1']} S2={counts['S2']} S3={counts['S3']}"
        )
        return

    if mode == "apply-s1":
        rows = _load_active(factory)
        groups = _s1_groups(rows)
        done = 0
        for (city, name), grp in sorted(groups.items()):
            grp = sorted(grp, key=_keeper_key)
            keeper, losers = grp[0], grp[1:]
            print(f"[{city}] {name}: keeper=[{keeper.source}] id={str(keeper.id)[:8]}")
            for loser in losers:
                for line in _merge_and_retire(factory, keeper, loser, "S1"):
                    print(line)
                done += 1
        print(f"\nretired {done} loser rows across {len(groups)} name groups")
        return

    if mode == "apply-group":
        keeper_id = uuid.UUID(sys.argv[2])
        loser_ids = [uuid.UUID(x) for x in sys.argv[3:]]
        with factory() as s:
            keeper = s.get(Poi, keeper_id)
            print(f"keeper=[{keeper.source}] {keeper.name_zh}")
            for lid in loser_ids:
                loser = s.get(Poi, lid)
                for line in _merge_and_retire(factory, keeper, loser, "group"):
                    print(line)
        return

    if mode == "apply-s2":
        dec_path = sys.argv[2]
        decisions: set[tuple[str, str]] = set()
        with open(dec_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    city, keeper_name = line.split("|", 1)
                    decisions.add((city.strip(), keeper_name.strip()))
        rows = _load_active(factory)
        by_city: dict[str, list[Poi]] = defaultdict(list)
        for r in rows:
            by_city[(r.city or "").strip().removesuffix("市")].append(r)
        groups: dict[tuple[str, str], list[Poi]] = defaultdict(list)
        for city, items in by_city.items():
            for r in items:
                core = _name_core(r.name_zh)
                if core and len(core) >= 2:
                    groups[(city, core)].append(r)
        applied = 0
        missing: list[tuple[str, str, list[Poi]]] = []
        used = set()
        for (city, core), grp in sorted(groups.items()):
            if len(grp) < 2:
                continue
            hits = [r for r in grp if (city, r.name_zh) in decisions]
            if not hits:
                detail = ", ".join(
                    f"[{r.source}] {r.name_zh} (rating={r.rating}, dur="
                    f"{r.suggested_duration_min}, tags={r.tags}) id={str(r.id)[:8]}"
                    for r in sorted(grp, key=_keeper_key)
                )
                missing.append((city, core, detail))
                continue
            keeper = hits[0]
            used.add((city, keeper.name_zh))
            print(f"[{city}|{core}] keeper=[{keeper.source}] {keeper.name_zh}")
            for loser in grp:
                if loser.id == keeper.id:
                    continue
                for line in _merge_and_retire(factory, keeper, loser, "S2"):
                    print(line)
                applied += 1
        unused = decisions - used
        print(
            f"\nretired {applied} loser rows; missing-decision groups: {len(missing)}"
        )
        for city, core, detail in missing:
            print(f"  MISSING [{city}|{core}] {detail}")
        if unused:
            print(f"unused decisions (check typos): {sorted(unused)}")
        return

    if mode == "s3-detail":
        rows = _load_active(factory)
        with factory() as s:
            geo = Poi.location.cast(Geometry)
            coord_map = {
                rid: (lon, lat)
                for rid, lon, lat in s.query(Poi.id, func.ST_X(geo), func.ST_Y(geo))
                .filter(Poi.status == "active")
                .all()
            }
        by_city: dict[str, list[Poi]] = defaultdict(list)
        for r in rows:
            by_city[(r.city or "").strip().removesuffix("市")].append(r)
        for city, items in sorted(by_city.items()):
            for i, a in enumerate(items):
                for b in items[i + 1 :]:
                    if a.name_zh == b.name_zh or (
                        _name_core(a.name_zh)
                        and (_name_core(a.name_zh) == _name_core(b.name_zh))
                    ):
                        continue
                    if not _name_overlap(a.name_zh, b.name_zh):
                        continue
                    d = _dist_m(coord_map.get(a.id), coord_map.get(b.id))
                    for r in (a, b):
                        lon, lat = coord_map.get(r.id) or (None, None)
                        print(
                            f"[{city}|dist={d}m] [{r.source}] {r.name_zh} "
                            f"(rating={r.rating}, tags={r.tags}, id={str(r.id)[:8]}) "
                            f"coord=({lon},{lat}) addr={r.address}"
                        )
        return

    if mode == "apply-s3":
        dec_path = sys.argv[2]
        triples: list[tuple[str, str, str]] = []
        with open(dec_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    city, keeper_name, loser_name = line.split("|", 2)
                    triples.append(
                        (city.strip(), keeper_name.strip(), loser_name.strip())
                    )
        done = 0
        for city, keeper_name, loser_name in triples:
            keeper = _find_active(factory, city, keeper_name)
            loser = _find_active(factory, city, loser_name)
            if keeper is None or loser is None:
                print(
                    f"SKIP 找不到 active 行: [{city}] "
                    f"keeper={keeper_name} loser={loser_name}"
                )
                continue
            print(f"[{city}] keeper=[{keeper.source}] {keeper.name_zh}")
            for line in _merge_and_retire(factory, keeper, loser, "S3"):
                print(line)
            done += 1
        print(f"\nretired {done} loser rows from {len(triples)} decisions")
        return

    print(__doc__)
    sys.exit(2)


if __name__ == "__main__":
    main()
