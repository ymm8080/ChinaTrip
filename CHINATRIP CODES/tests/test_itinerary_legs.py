"""Adjacent-stop leg annotation (v2.4.3 §5 行程时间轴) — unit tests."""

from datetime import time

import pytest

from app.services.itinerary.legs import annotate_legs
from app.services.itinerary.models import (
    DayPlan,
    DiffOp,
    GeoPoint,
    ItineraryPlan,
    TransferItem,
    VisitItem,
)
from app.services.itinerary.pipeline import mutate


def _visit(name: str, lon: float | None, lat: float | None) -> VisitItem:
    return VisitItem(
        item_id=f"v-{name}",
        name=name,
        city="北京",
        day=1,
        location=GeoPoint(lon=lon, lat=lat) if lon is not None else None,
    )


def _plan(*items: VisitItem | TransferItem) -> ItineraryPlan:
    return ItineraryPlan(
        itinerary_id="it-x",
        cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=list(items))],
    )


def test_adjacent_visits_get_distance_and_walk_estimate():
    plan = _plan(_visit("A", 116.40, 39.90), _visit("B", 116.41, 39.90))
    annotate_legs(plan)
    a, b = plan.days[0].items
    assert a.distance_to_next_km == pytest.approx(0.85, abs=0.05)
    assert a.next_walk_minutes == pytest.approx(14, abs=4)
    assert a.leg_source == "estimate"
    # last stop of the day has no outgoing leg
    assert b.distance_to_next_km is None
    assert b.next_walk_minutes is None


def test_transfer_breaks_the_leg_chain():
    hop = TransferItem(item_id="t1", day=1, seq=1, from_city="北京", to_city="上海")
    plan = _plan(_visit("A", 116.40, 39.90), hop, _visit("B", 116.41, 39.90))
    annotate_legs(plan)
    a, _, b = plan.days[0].items
    # the transfer card owns that leg; no straight-line annotation across it
    assert a.distance_to_next_km is None
    assert b.distance_to_next_km is None


def test_missing_location_leaves_leg_unset():
    plan = _plan(_visit("A", None, None), _visit("B", 116.41, 39.90))
    annotate_legs(plan)
    a, b = plan.days[0].items
    assert a.distance_to_next_km is None
    assert b.distance_to_next_km is None


def test_colocated_stops_stay_unannotated():
    plan = _plan(_visit("A", 116.40, 39.90), _visit("B", 116.4001, 39.90))
    annotate_legs(plan)
    a, _ = plan.days[0].items
    assert a.distance_to_next_km is None


def test_annotation_is_idempotent():
    plan = _plan(_visit("A", 116.40, 39.90), _visit("B", 116.42, 39.90))
    annotate_legs(plan)
    snapshot = plan.model_copy(deep=True)
    annotate_legs(plan)
    assert plan == snapshot


def test_mutate_pipeline_output_is_annotated():
    plan = _plan(
        VisitItem(
            item_id="v-A",
            name="A",
            city="北京",
            day=1,
            location=GeoPoint(lon=116.40, lat=39.90),
            start_time=time(9, 0),
            duration_minutes=60,
        ),
        VisitItem(
            item_id="v-B",
            name="B",
            city="北京",
            day=1,
            location=GeoPoint(lon=116.41, lat=39.90),
            start_time=time(11, 0),
            duration_minutes=60,
        ),
    )
    new_plan, report, _ = mutate(
        plan,
        [DiffOp(op="retime", item_id="v-A", new_start_time=time(10, 0))],
        poi_hours=[],
    )
    assert report.ok
    a = next(i for i in new_plan.days[0].items if i.item_id == "v-A")
    assert a.distance_to_next_km is not None
    assert a.next_walk_minutes is not None
