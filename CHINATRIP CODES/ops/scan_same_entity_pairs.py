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

判定复用 poi_alternatives 同体闸的剥尾规则；台账输出 utf-8。
"""

from __future__ import annotations

import io
import os
import sys
import uuid
from collections import defaultdict

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
        # 3) 别名并入
        aliases = list(k.name_aliases or [])
        new = {loser_row.name_zh, *(a for a in (loser_row.name_aliases or []) if a)}
        added = [a for a in sorted(new) if a not in aliases and a != k.name_zh]
        if added:
            aliases.extend(added)
            k.name_aliases = aliases
            ops.append(f"    aliases += {added}")
        # 4) 退役
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

    print(__doc__)
    sys.exit(2)


if __name__ == "__main__":
    main()
