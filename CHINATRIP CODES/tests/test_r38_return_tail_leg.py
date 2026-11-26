# -*- coding: utf-8 -*-
"""R38 (2026-11-25): the return-to-city → next-stop tail is a first-class leg.

Three user reports in one shape (day3 慕田峪, live sessions dab1fa37/29173f5d):

1. C-08's after-return branch anchored the following stop at
   ``min(rets)+ride+last_mile`` (earliest timetable bus 14:30) instead of the
   actually-chosen return bus (16:30, arriving 18:08) — 奥园 could open at
   17:30, 38 minutes BEFORE the traveller is back in the city; the
   alight→next-stop taxi tail never entered the constraint at all.
2. The projected return card carried no tail leg and the hint stopped at the
   alight stop — on screen「回城 18:00 到前门」was followed directly by the
   next sight card with no transit between (and the gap-bridge pass refuses
   transfer endpoints). Now the return card carries the tail taxi leg and the
   hint spells out「打车约N分 → 下一站」.
3. Train transfer cards carried no stations although the train cache always
   has them (北京南 → 上海虹桥, not just 北京 → 上海).
"""

from __future__ import annotations

import asyncio
from datetime import time
from types import SimpleNamespace

import pytest
from ortools.sat.python import cp_model

from app.services.itinerary.legs import (
    _return_hint_text,
    attach_return_cards,
)
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    VisitItem,
)
from app.services.itinerary.rules import travel_gap_violations
from app.services.trip_solver.model.c05_c08 import (
    _return_tail_minutes,
    add_c08_access,
)
from app.services.trip_solver.types import AccessProfile

# ---------------------------------------------------------------------------
# 1) C-08 after-return anchor: chosen bus + taxi tail, not earliest bus
# ---------------------------------------------------------------------------

PROFILE = AccessProfile(
    gateway="前门",
    to_poi="远山景区",
    ride_minutes=90,
    wait_minutes=10,
    last_mile_minutes=8,
    departures=("08:30",),
    returns=("14:30", "15:30", "16:30"),
    taxi_minutes=15,
)


def _solve_day(mutianyu_dur: int) -> tuple[int, int]:
    """Solve a 1-day world: remote cM (profiled) + city stop cX on the same day.

    Returns (ret_value, cx_start). With dur=330 the visit ends past the
    14:30/15:30 buses so the solver MUST pick the 16:30 bus (ret=990).
    """
    m = cp_model.CpModel()
    presence = {
        ("cM", 1): m.NewBoolVar("p_cM"),
        ("cX", 1): m.NewBoolVar("p_cX"),
    }
    start = {
        ("cM", 1): m.NewIntVar(0, 1440, "s_cM"),
        ("cX", 1): m.NewIntVar(0, 1440, "s_cX"),
    }
    dur = {"cM": mutianyu_dur, "cX": 90}
    bundle = SimpleNamespace(
        model=m,
        presence=presence,
        start=start,
        dur=dur,
        days=(1,),
        dep_vars={},
        arrival_vars={},
        ret_vars={},
        active_ret_vars={},
        active_dep_vars={},
        travel_terms=[],
    )
    cands = [
        SimpleNamespace(
            cid="cM",
            rid="r_cM",
            poi_id="poi_cM",
            category="sight",
            city="北京",
            lon=116.60,
            lat=40.40,
        ),
        SimpleNamespace(
            cid="cX",
            rid="r_cX",
            poi_id="poi_cX",
            category="sight",
            city="北京",
            lon=116.42,
            lat=39.93,
        ),
    ]
    enriched = SimpleNamespace(
        snapshot=SimpleNamespace(
            candidates=cands,
            request=SimpleNamespace(pins=(), musts=()),
        ),
        access_by_poi={"poi_cM": PROFILE},
    )
    add_c08_access(bundle, enriched)
    # C-08 pins arrival (dep+ride+last_mile=608) but the visit-start floor
    # lives in the generic chain/F-22 constraints — pin it so the world is
    # deterministic: visit 10:08-15:38, +8 buffer → the 16:30 bus is forced.
    m.Add(start[("cM", 1)] == 8 * 60 + 30 + 90 + 8)
    m.Add(presence[("cM", 1)] == 1)
    m.Add(presence[("cX", 1)] == 1)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10.0
    status = solver.Solve(m)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    ret_val = solver.Value(bundle.ret_vars[("cM", 1)])
    cx_start = solver.Value(start[("cX", 1)])
    return ret_val, cx_start


def test_c08_anchors_next_stop_on_chosen_bus_plus_tail():
    ret, cx_start = _solve_day(mutianyu_dur=330)
    # The visit ends 608+330=938, +8 buffer → earliest feasible bus is 16:30.
    assert ret == 990, "test world must force the 16:30 bus, got %s" % ret
    tail = _return_tail_minutes(SimpleNamespace(city="北京", lon=116.42, lat=39.93))
    assert tail > 0
    # Old code anchored at min(rets)=870 → floor 968 (16:08); 奥园 17:30 case.
    # New floor = ret(990) + ride(90) + last_mile(8) + tail → 18:08 + tail.
    assert cx_start >= ret + 90 + 8 + tail, (
        "next stop may not open before the actual return arrival + taxi tail"
    )


def test_c08_tail_is_zero_for_venue_adjacent_stop():
    # Same-venue (≤0.5km of the city anchor) next stop: no tail minutes.
    # 北京 anchor = (39.9042, 116.4074); this point is ~0.4km away.
    assert (
        _return_tail_minutes(SimpleNamespace(city="北京", lon=116.4104, lat=39.9072))
        == 0
    )


def test_c08_tail_falls_back_to_floor_without_coords():
    from app.services.itinerary.rules import TRAVEL_GAP_FLOOR_MIN

    assert (
        _return_tail_minutes(SimpleNamespace(city="北京", lon=None, lat=None))
        == TRAVEL_GAP_FLOOR_MIN
    )


# ---------------------------------------------------------------------------
# 2) Hint + return card carry the tail leg
# ---------------------------------------------------------------------------


def test_return_hint_appends_taxi_tail_to_next_stop():
    hint = _return_hint_text(
        {
            "depart_time": "16:30",
            "arrive_time": "18:08",
            "alight": "前门大街北口",
            "next_stop": "北京奥林匹克公园",
            "taxi_minutes": 28,
            "taxi_km": 11.75,
        }
    )
    text = str(hint)
    assert "18:08 到 前门大街北口" in text
    assert "打车约28分 → 北京奥林匹克公园" in text


def test_return_hint_unchanged_without_tail():
    # Terminal-return shape (next_stop == alight, no taxi tail) stays clean.
    hint = _return_hint_text(
        {
            "depart_time": "16:30",
            "arrive_time": "18:08",
            "alight": "前门大街北口",
            "next_stop": "前门大街北口",
            "taxi_minutes": 0,
        }
    )
    text = str(hint)
    assert "打车" not in text and "taxi" not in text


def _site_plan():
    site = VisitItem(
        item_id="v7",
        name="远山景区",
        city="北京",
        day=3,
        category="attraction",
        duration_minutes=240,
        location=GeoPoint(lon=116.60, lat=40.40),
        start_time=time(12, 8),
        end_time=time(16, 8),
        next_leg_mode="access",
        next_leg_minutes=140,
        distance_to_next_km=12.0,
        next_leg_cost_cny=100,
        next_leg_detail={
            "mode": "access",
            "direction": "return",
            "taxi_km": 11.75,
            "taxi_minutes": 28,
            "taxi_rush_note": "",
            "wait_minutes": 8,
            "service_minutes": 90,
            "walk_minutes": 8,
            "gateway": "前门",
            "alight": "前门大街北口",
            "next_stop": "北京奥林匹克公园",
            "service_name": "慕田峪专线",
            "departures": ["07:30", "08:30", "09:30", "10:30"],
            "returns": ["14:30", "15:30", "16:30"],
            "fare_text": "¥80",
            "board_time": "16:16",
            "next_item_id": "v8",
            "depart_time": "16:30",
            "arrive_time": "18:08",
            "taxi_cost": 35,
            "access_cost": 80,
            "booking_url": None,
            "official_url": None,
            "to_city": True,
        },
    )
    nxt = VisitItem(
        item_id="v8",
        name="北京奥林匹克公园",
        city="北京",
        day=3,
        category="attraction",
        duration_minutes=90,
        location=GeoPoint(lon=116.42, lat=39.93),
        start_time=time(18, 45),
        end_time=time(20, 15),
    )
    plan = ItineraryPlan(
        itinerary_id="t38",
        cities=["北京"],
        days=[DayPlan(day=3, base_city="北京", items=[site, nxt])],
        assumptions=[],
    )
    return plan, site


def test_return_card_carries_tail_leg_fields():
    plan, _site = _site_plan()
    out = attach_return_cards(plan)
    day = out.days[0]
    card = next(
        (i for i in day.items if str(i.item_id).startswith("access-return-")),
        None,
    )
    assert card is not None
    assert card.next_leg_mode == "taxi"
    assert card.next_leg_minutes == 28
    assert card.distance_to_next_km == pytest.approx(11.75, abs=0.01)
    assert card.next_leg_cost_cny == 35
    # The origin site keeps its hint (with the tail spelled out); the next
    # stop itself is untouched (its own legs belong to the annotate chain).
    assert card.next_leg_detail.get("owner_item_id") == "v7"


def test_return_card_without_tail_stays_bare():
    plan, site = _site_plan()
    site.next_leg_detail = dict(site.next_leg_detail)
    site.next_leg_detail["taxi_minutes"] = 0
    site.next_leg_detail["taxi_km"] = 0.0
    out = attach_return_cards(plan)
    card = next(
        (i for i in out.days[0].items if str(i.item_id).startswith("access-return-")),
        None,
    )
    assert card is not None
    assert card.next_leg_mode is None
    assert card.distance_to_next_km is None


# ---------------------------------------------------------------------------
# 3) Iron rule 7 sees through synthetic no-coords cards
# ---------------------------------------------------------------------------


def _v3(item_id, name, start, end, lon, lat):
    return VisitItem(
        item_id=item_id,
        name=name,
        city="北京",
        day=3,
        category="attraction",
        duration_minutes=(end.hour * 60 + end.minute)
        - (start.hour * 60 + start.minute),
        location=GeoPoint(lon=lon, lat=lat) if lon else None,
        start_time=start,
        end_time=end,
    )


def _day3_items(cx_start: time):
    remote = _v3("v7", "甲山景区", time(12, 8), time(16, 8), 116.60, 40.40)
    ret_card = VisitItem(
        item_id="access-return-v7",
        name="🚌 回城",
        city="北京",
        day=3,
        category="transfer",
        duration_minutes=90,
        location=None,
        start_time=time(16, 30),
        end_time=time(18, 0),
        synthetic=True,
    )
    nxt = _v3("v8", "乙园", cx_start, time(20, 0), 116.40, 39.95)
    return [remote, ret_card, nxt]


def test_rule7_sees_through_synthetic_return_card():
    # 57km-ish chain needs ~79 min; 16:08 → 17:00 gap=52 → violation reported
    # across the synthetic card (old code: 0 violations, blind).
    violations = travel_gap_violations(3, _day3_items(time(17, 0)))
    assert violations, "rule7 must not be blinded by the synthetic return card"
    ids = {i for v in violations for i in v.item_ids}
    assert "v7" in ids and "v8" in ids


def test_rule7_passes_when_gap_covers_chain():
    violations = travel_gap_violations(3, _day3_items(time(18, 50)))
    assert violations == []


# ---------------------------------------------------------------------------
# 4) Train transfer cards carry the stations
# ---------------------------------------------------------------------------


def test_build_transfer_item_fills_stations():
    from app.services.trains import TrainOption, build_transfer_item

    class _Svc:
        async def search(self, a, b, date):
            return [
                TrainOption(
                    train_no="G1",
                    dep_time=time(8, 30),
                    arr_time=time(13, 0),
                    duration_minutes=270,
                    from_station="北京南",
                    to_station="上海虹桥",
                    from_city=a,
                    to_city=b,
                    date=date,
                )
            ]

    leg = asyncio.run(
        build_transfer_item(
            _Svc(),
            from_city="北京",
            to_city="上海",
            date="2026-12-01",
            day=1,
            seq=0,
            item_id="xfer-t",
        )
    )
    assert leg is not None
    assert leg.from_station == "北京南"
    assert leg.to_station == "上海虹桥"
    payload = leg.model_dump()
    assert payload["from_station"] == "北京南"
    # Synthetic/intake legs have no stations — the field stays optional.
    bare = leg.model_copy(update={"from_station": None, "to_station": None})
    assert bare.from_station is None
