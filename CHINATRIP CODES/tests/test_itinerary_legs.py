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
    # 已排时刻（2026-11-03 无时刻卡不得交付后，腿链以已排卡为前提）：
    # None-None 卡断链（leg_pairs），旧夹具全裸卡不再成对。
    return VisitItem(
        item_id=f"v-{name}",
        name=name,
        city="北京",
        day=1,
        start_time=time(9, 0),
        end_time=time(10, 0),
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


def _meal_placeholder(start: time = time(12, 20)) -> VisitItem:
    return VisitItem(
        item_id="food-lunch-ph-d1",
        name="午饭（自由安排）",
        category="food",
        city="西安",
        day=1,
        start_time=start,
        end_time=time(start.hour, start.minute + 30),
        duration_minutes=30,
        anchor_from_prev=True,
    )


def test_blank_lunch_card_inherits_previous_stop_address():
    """2026-11-13 西安 D2 案：秦俑情 12:20 散场 → 「午饭（自由安排）」空白
    卡（无地址、无腿）→ 华清宫。空卡须吃上一站地址，「餐 → 下一站」照算。"""
    site = _visit("《秦俑情》", 109.2808, 34.3804)
    site.address = "陕西省西安市临潼区秦陵街道秦俑村村委会"
    site.end_time = time(12, 20)
    lunch = _meal_placeholder()
    nxt = _visit("华清宫", 109.2150, 34.3588)
    nxt.start_time = time(13, 4)
    plan = _plan(site, lunch, nxt)
    annotate_legs(plan)
    assert lunch.address == site.address
    # 与上一站同址 → 进餐卡的腿不显示（0km），卡片地址仍继承
    assert site.distance_to_next_km is None
    # 餐卡 → 下一站的腿现在算得出来
    assert lunch.distance_to_next_km is not None
    assert lunch.next_walk_minutes is not None
    assert lunch.leg_source == "estimate"


def test_meal_card_without_previous_stop_stays_blank():
    lunch = _meal_placeholder()
    nxt = _visit("华清宫", 109.2150, 34.3588)
    nxt.start_time = time(13, 4)
    plan = _plan(lunch, nxt)
    annotate_legs(plan)
    assert lunch.address is None
    assert lunch.distance_to_next_km is None


def test_legacy_meal_card_is_adopted_on_refresh():
    """旧行程自愈：上线前落库的午饭占位卡没有 anchor_from_prev 标记，
    refresh_legs 补标后同一回合 annotate 即回填上一站地址。"""
    from app.services.agent.plan import PlanningAgent

    site = _visit("《秦俑情》", 109.2808, 34.3804)
    site.address = "陕西省西安市临潼区秦陵街道秦俑村村委会"
    site.end_time = time(12, 20)
    legacy = _meal_placeholder()
    legacy.anchor_from_prev = False  # 旧载荷形态
    plan = _plan(site, legacy)
    PlanningAgent._adopt_legacy_meal_anchors(plan)
    annotate_legs(plan)
    assert legacy.address == site.address
    assert legacy.anchor_location == site.location


def test_meal_card_anchor_resets_across_transfer():
    site = _visit("A", 116.40, 39.90)
    site.address = "A 地址"
    site.end_time = time(10, 0)
    hop = TransferItem(item_id="t1", day=1, seq=1, from_city="北京", to_city="上海")
    lunch = _meal_placeholder(start=time(13, 0))
    plan = _plan(site, hop, lunch)
    annotate_legs(plan)
    # 换乘卡之后不继承出发城地址
    assert lunch.address is None


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
            start_time=time(11, 45),
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
