"""同址餐饮融合（2026-11-12 用户拍板）：街区天然有餐饮，不应该互斥相撞。

「近距离地址的街区和景点天然相容的...特别是餐厅的地址就在街区里。。
那么街区的时间里就包含了餐厅时间」——同址（≤SAME_VENUE_KM）的一张
food 卡可整体嵌进同日非餐宿主卡的时段窗：solver 不判双订、不记走行、
强偏好嵌套；rules 铁律 1 对嵌套对豁免。全部类级谓词，不认卡型/城市。
"""

from datetime import time

from app.services.itinerary.models import DayPlan, GeoPoint, ItineraryPlan, VisitItem
from app.services.itinerary.rules import validate_plan
from app.services.itinerary.solver import (
    SAME_VENUE_KM,
    fusion_food_nested,
    insertion_schedule_day,
    is_same_venue_food_pair,
)

# 同一街区院内两点（≈0.1km）/ 圈外一点（3km）
_BLOCK_XY = GeoPoint(lon=108.9510, lat=34.2190)
_COLOCATED_XY = GeoPoint(lon=108.9520, lat=34.2190)  # ≈0.09km
_FAR_XY = GeoPoint(lon=108.9800, lat=34.2190)  # ≈3km


def _food(name: str, xy: GeoPoint, dur: int = 60, **kw) -> VisitItem:
    return VisitItem(
        item_id=f"v-{name}",
        name=name,
        poi_id=f"curated:测试城:{name}",
        category="food",
        city="测试城",
        location=xy,
        day=1,
        duration_minutes=dur,
        opening_hours="午宴12:30场；晚宴18:30场（预订制）",
        **kw,
    )


def _host(name: str, xy: GeoPoint, dur: int = 240, **kw) -> VisitItem:
    return VisitItem(
        item_id=f"v-{name}",
        name=name,
        poi_id=f"curated:测试城:{name}",
        category="citywalk",
        city="测试城",
        location=xy,
        day=1,
        duration_minutes=dur,
        **kw,
    )


# ---- 谓词：同址融合对 -----------------------------------------------------


def test_pair_food_and_host_same_venue():
    assert is_same_venue_food_pair(
        _food("同址宴", _COLOCATED_XY), _host("主题街区", _BLOCK_XY)
    )


def test_pair_rejects_both_food():
    other = _food("别家餐", _COLOCATED_XY)
    assert not is_same_venue_food_pair(_food("同址宴", _COLOCATED_XY), other)


def test_pair_rejects_both_non_food():
    assert not is_same_venue_food_pair(
        _host("主题街区", _BLOCK_XY), _host("邻馆", _COLOCATED_XY)
    )


def test_pair_rejects_hotel_host():
    hotel = VisitItem(
        item_id="v-hotel",
        name="酒店",
        category="hotel",
        city="测试城",
        location=_COLOCATED_XY,
        day=1,
    )
    assert not is_same_venue_food_pair(_food("同址宴", _COLOCATED_XY), hotel)


def test_pair_rejects_beyond_same_venue_radius():
    edge = GeoPoint(lon=_BLOCK_XY.lon + 0.01, lat=_BLOCK_XY.lat)  # ≈0.95km
    pair = is_same_venue_food_pair(_food("近距餐", edge), _host("主题街区", _BLOCK_XY))
    assert not pair
    assert SAME_VENUE_KM < 0.95


def test_pair_rejects_missing_location():
    no_loc = _food("无坐标餐", _COLOCATED_XY)
    no_loc = no_loc.model_copy(update={"location": None})
    assert not is_same_venue_food_pair(no_loc, _host("主题街区", _BLOCK_XY))


def test_nested_requires_full_containment():
    food = _food("同址宴", _COLOCATED_XY)
    host = _host("主题街区", _BLOCK_XY)
    block_span = (17 * 60, 21 * 60)
    # 完整包含 → 嵌套豁免
    dinner_span = (18 * 60 + 30, 19 * 60 + 30)
    assert fusion_food_nested(food, host, dinner_span, block_span)
    # 部分溢出（餐跨过宿主窗尾）→ 不豁免
    spill_span = (20 * 60 + 30, 21 * 60 + 30)
    assert not fusion_food_nested(food, host, spill_span, block_span)
    # 远距离对 → 不豁免
    far_food = _food("远餐", _FAR_XY)
    assert not fusion_food_nested(far_food, host, dinner_span, block_span)


# ---- solver：同址声明场次宴秀嵌进街区窗 ------------------------------------


def _day_with(items: list[VisitItem]) -> DayPlan:
    return DayPlan(day=1, base_city="测试城", items=items)


def test_solver_nests_declared_banquet_inside_same_venue_block():
    # 用户案类级回归（西安·唐宴 0.1km 街区）：声明 12:30/18:30 两场的同址
    # 宴秀，街区卡 17:00-21:00 已锚——18:30 场应嵌进街区窗（融合强偏好压
    # 过 12:30 独立餐位），而不是互斥相撞排去午餐。
    block = _host(
        "某主题街区",
        _BLOCK_XY,
        pinned=True,
        start_time=time(17, 0),
        end_time=time(21, 0),
    )
    banquet = _food("同址主题宴", _COLOCATED_XY)
    out = insertion_schedule_day(_day_with([block, banquet]), poi_hours=[])
    assert out is not None
    placed = {i.name: i for i in out.items}
    assert placed["某主题街区"].start_time == time(17, 0)
    got = placed["同址主题宴"]
    assert got.start_time == time(18, 30), (
        f"应嵌进街区窗的 18:30 场，实得 {got.start_time}"
    )
    assert got.end_time == time(19, 30)


def test_solver_far_banquet_cannot_nest_and_uses_early_session():
    # 对照：3km 外同文案宴秀与街区窗相撞 → 融合豁免不成立（非同址），
    # 18:30 场被双订闸弹回，回落 12:30 独立场。
    block = _host(
        "某主题街区",
        _BLOCK_XY,
        pinned=True,
        start_time=time(17, 0),
        end_time=time(21, 0),
    )
    banquet = _food("远郊主题宴", _FAR_XY)
    out = insertion_schedule_day(_day_with([block, banquet]), poi_hours=[])
    assert out is not None
    placed = {i.name: i for i in out.items}
    got = placed["远郊主题宴"]
    assert got.start_time == time(12, 30), (
        f"远距不得嵌套，应回落 12:30，实得 {got.start_time}"
    )


# ---- rules：铁律 1 对嵌套融合对豁免 ----------------------------------------


def _plan_with(food_xy: GeoPoint, food_span: tuple[int, int]) -> ItineraryPlan:
    host = _host(
        "某主题街区",
        _BLOCK_XY,
        start_time=time(17, 0),
        end_time=time(21, 0),
    )
    fs, fe = food_span
    food = _food(
        "同址主题宴",
        food_xy,
        start_time=time(fs // 60, fs % 60),
        end_time=time(fe // 60, fe % 60),
    )
    return ItineraryPlan(
        itinerary_id="test-fusion", cities=["测试城"], days=[_day_with([host, food])]
    )


def test_rule1_exempts_nested_same_venue_food():
    plan = _plan_with(_COLOCATED_XY, (18 * 60 + 30, 19 * 60 + 30))
    report = validate_plan(plan, poi_hours=[])
    assert not [v for v in report.violations if v.rule_id == 1], (
        f"嵌套融合不应判双订: {report.violations}"
    )


def test_rule1_still_fires_on_far_overlap():
    plan = _plan_with(_FAR_XY, (18 * 60 + 30, 19 * 60 + 30))
    report = validate_plan(plan, poi_hours=[])
    assert any(v.rule_id == 1 for v in report.violations), "远距重叠仍须判双订"


def test_rule1_still_fires_on_spill_beyond_host_window():
    # 同址但餐溢出街区窗尾（20:30-21:30 vs 17:00-21:00）→ 不豁免
    plan = _plan_with(_COLOCATED_XY, (20 * 60 + 30, 21 * 60 + 30))
    report = validate_plan(plan, poi_hours=[])
    assert any(v.rule_id == 1 for v in report.violations), "溢出窗尾仍须判双订"


def test_rule1_still_fires_on_plain_meal_overlap():
    # 无声明场次的普通餐卡（2026-11-10 并块尾机制管辖）不占同址宿主窗：
    # 嵌套豁免只认声明场次餐，普通餐重叠照旧判双订。
    host = _host(
        "某主题街区",
        _BLOCK_XY,
        start_time=time(17, 0),
        end_time=time(21, 0),
    )
    plain = _food("同址普通晚餐", _COLOCATED_XY)
    plain = plain.model_copy(
        update={
            "opening_hours": None,
            "start_time": time(18, 30),
            "end_time": time(19, 30),
        }
    )
    plan = ItineraryPlan(
        itinerary_id="test-fusion",
        cities=["测试城"],
        days=[_day_with([host, plain])],
    )
    report = validate_plan(plan, poi_hours=[])
    assert any(v.rule_id == 1 for v in report.violations), (
        "普通餐重叠仍须判双订（嵌套豁免只管声明场次餐）"
    )
