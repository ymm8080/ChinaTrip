# -*- coding: utf-8 -*-
"""R37 (2026-11-24): must-visits are not demoted by the evening-gate evictor.

R35's rule (musts outrank the daytime entry band) previously lived only
in ``enforce_entry_gate``; ``_evict_evening_gate_breachers`` (2026-11-17)
still evicted every breacher to unplaced. Live probe (慕田峪 D1 + 八达岭
D2 + 国家体育场（鸟巢）): the solver placed 鸟巢 16:35 in the R36
after-return escape slot on the 八达岭 day, then this gate demoted it
(「晚闸 16:00 后不再入场」) — the last mile of the R33/R35 whack-a-mole.
Musts now stay (with disclosure); non-musts keep getting evicted.
"""

from datetime import time

from app.services.agent.plan import _evict_evening_gate_breachers
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    VisitItem,
)


def _v(item_id, name, start, end, *, cat="attraction", **kw):
    dur = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
    return VisitItem(
        item_id=item_id,
        name=name,
        city="北京",
        day=1,
        category=cat,
        duration_minutes=kw.pop("dur", dur),
        location=GeoPoint(lon=116.4, lat=39.9),
        start_time=start,
        end_time=end,
        **kw,
    )


def _plan(items):
    return ItineraryPlan(
        itinerary_id="t37",
        cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=items)],
        assumptions=[],
    )


def test_must_kept_with_disclosure_evening_gate():
    # 鸟巢 live 形状：90min 大点、封闭窗、16:35 开场（返程后逃逸位）
    plan = _plan(
        [
            _v(
                "nest",
                "鸟巢(国家体育场)",
                time(16, 35),
                time(18, 5),
                poi_id="ct_15",
                opening_hours="周一至周日 08:00-22:00",
                must=True,
            )
        ]
    )
    notes = _evict_evening_gate_breachers(plan)
    item = plan.days[0].items[0]
    assert item.name == "鸟巢(国家体育场)"
    assert item.start_time == time(16, 35)
    assert not plan.unplaced
    assert notes and "鸟巢(国家体育场)" in notes[0]
    assert "保留晚间时刻" in notes[0]


def test_non_must_still_evicted_evening_gate():
    plan = _plan(
        [
            _v(
                "jas",
                "静安寺",
                time(16, 35),
                time(18, 5),
                poi_id="jas",
                opening_hours="周一至周日 08:00-22:00",
            )
        ]
    )
    notes = _evict_evening_gate_breachers(plan)
    assert notes
    assert plan.unplaced and plan.unplaced[0].reason == "evening_gate"
    assert plan.days[0].items == []


def test_second_run_appends_no_new_note():
    plan = _plan(
        [
            _v(
                "nest",
                "鸟巢(国家体育场)",
                time(16, 35),
                time(18, 5),
                poi_id="ct_15",
                opening_hours="周一至周日 08:00-22:00",
                must=True,
            )
        ]
    )
    first = _evict_evening_gate_breachers(plan)
    assert first
    plan.assumptions = list(first)
    second = _evict_evening_gate_breachers(plan)
    assert second == []
    assert plan.days[0].items and plan.days[0].items[0].must is True
