# -*- coding: utf-8 -*-
"""R33: the daytime entry gate must not demote a must-visit that the solver
deliberately placed in C-06's after-remote-return slot.

Before R33 the gate cleared such cards to untimed, then the coverage audit
demoted them to unplaced (鸟巢(国家体育场) after 慕田峪长城 on a user-written
day). The exemption is narrow: must-visits only, only after a real return
card, and only when they would otherwise breach the cap.
"""

from datetime import time

from app.services.agent.plan import _after_remote_return, enforce_entry_gate
from app.services.itinerary.models import DayPlan, GeoPoint, ItineraryPlan, VisitItem


def _visit(name, start, end, *, item_id="v1", must=True, category="attraction"):
    return VisitItem(
        item_id=item_id,
        name=name,
        poi_id="poi-r33-%s" % item_id,
        category=category,
        city="北京",
        day=1,
        start_time=start,
        end_time=end,
        must=must,
        duration_minutes=90,
        opening_hours="10:00-22:00",
        location=GeoPoint(lon=116.4, lat=39.9),
    )


def _return_card(end=time(16, 8)):
    return VisitItem(
        item_id="access-return-v1",
        name="回城",
        category="transfer",
        city="北京",
        day=1,
        start_time=time(14, 30),
        end_time=end,
    )


def _plan(*items):
    return ItineraryPlan(
        itinerary_id="t33",
        cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=list(items))],
    )


def test_after_remote_return_detection():
    late = _visit("鸟巢", time(18, 23), time(19, 53))

    def day(*items):
        return DayPlan(day=1, base_city="北京", items=list(items))

    assert _after_remote_return(day(_return_card(), late), late)
    assert not _after_remote_return(day(late), late)
    early = _visit("鸟巢", time(15, 0), time(16, 30))
    assert not _after_remote_return(day(_return_card(), early), early)


def test_late_must_after_return_keeps_time_with_disclosure():
    late = _visit("鸟巢(国家体育场)", time(18, 23), time(19, 53), item_id="v3")
    plan = _plan(_return_card(), late)
    notes = enforce_entry_gate(plan)
    assert late.start_time == time(18, 23)
    assert len(notes) == 1
    assert "鸟巢(国家体育场)" in notes[0]
    # idempotent on repeated gates (caller persists the notes as assumptions)
    plan.assumptions.extend(notes)
    assert enforce_entry_gate(plan) == []


def test_late_must_without_return_still_cleared():
    late = _visit("鸟巢(国家体育场)", time(18, 23), time(19, 53), item_id="v3")
    plan = _plan(late)
    notes = enforce_entry_gate(plan)
    assert late.start_time is None
    assert notes and "停止入场" in notes[0]


def test_late_non_must_after_return_still_cleared():
    late = _visit("补点", time(18, 23), time(19, 53), item_id="f1", must=False)
    plan = _plan(_return_card(), late)
    notes = enforce_entry_gate(plan)
    assert late.start_time is None
    assert notes and "停止入场" in notes[0]


def test_return_card_after_visit_does_not_exempt():
    late = _visit("鸟巢", time(15, 0), time(16, 30), item_id="v3")
    plan = _plan(late, _return_card(end=time(18, 0)))
    # 15:00 is inside the cap anyway; no note either way.
    assert enforce_entry_gate(plan) == []
    assert late.start_time == time(15, 0)
