# -*- coding: utf-8 -*-
"""全对象路途计腿拍板回归（2026-11-13 用户案：Day4 秦俑情 11:00 开场
80 分钟，散场 12:20，下一站醉长安 41 公里——旧引擎按「餐贴点/钉点」
类目豁免把零车程排程放行且永不披露）。

拍板：路途时间和距离在所有 OBJECT 里都要正确计算（HOTEL/餐饮/活动/
景点）。豁免只留两个类级口径：同址（≤SAME_VENUE_KM）与无坐标。

覆盖：
① 铁律 7：演出（钉）→远距餐厅（餐）零间隔必报；
② travel_gap_needed：同址餐对免、远距餐/钉照算、无坐标免；
③ 兜底排序：已排餐/酒店锚之后落位须留打车腿；
④ solver 矩阵：餐/酒店 located 对与观光同口径（≥30 地板）。
"""

from datetime import time as _t

from app.services.agent.plan import _fallback_sequence_times, _travel_matrix
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    VisitItem,
)
from app.services.itinerary.rules import (
    haversine_km,
    taxi_leg_min,
    travel_gap_needed,
    validate_plan,
)
from app.services.itinerary.solver import insertion_schedule_day

# 真实库位：兵马俑（临潼）与西安城心（钟楼）——直线 ~34km（用户实测
# 路程 41km），打车模型腿 = min(180, km*1.3/35*60+30) ≈ 105 分钟。
BINGMAYONG = GeoPoint(lon=109.2785, lat=34.3843)
ZHONGLou = GeoPoint(lon=108.9426, lat=34.2611)
_KM = haversine_km(BINGMAYONG, ZHONGLou)


def _show() -> VisitItem:
    return VisitItem(
        item_id="show-qinyong",
        name="《秦俑情》",
        city="西安",
        day=4,
        category="entertainment",
        best_visit_time="show",
        duration_minutes=80,
        pinned=True,  # 场次钉（引擎/用户皆走钉通道）
        start_time=_t(11, 0),
        end_time=_t(12, 20),
        opening_hours="多场（约11:00/17:00，以当日公告为准）",
        location=BINGMAYONG,
    )


def _restaurant() -> VisitItem:
    return VisitItem(
        item_id="food-zuichangan",
        name="醉长安",
        city="西安",
        day=4,
        category="food",
        duration_minutes=90,
        start_time=_t(12, 20),  # 散场即开场：零车程事故形态
        end_time=_t(13, 50),
        location=ZHONGLou,
    )


def _plan(*items: VisitItem) -> ItineraryPlan:
    return ItineraryPlan(
        itinerary_id="it-qinyong",
        cities=["西安"],
        days=[DayPlan(day=4, base_city="西安", items=list(items))],
        assumptions=[],
    )


# --- ① 铁律 7：钉演出→远距餐零间隔必报 -------------------------------


def test_rule7_flags_pinned_show_to_far_restaurant_zero_gap():
    plan = _plan(_show(), _restaurant())
    report = validate_plan(plan, poi_hours=[])
    rule7 = [v for v in report.violations if v.rule_id == 7]
    assert any(set(v.item_ids) == {"show-qinyong", "food-zuichangan"} for v in rule7), (
        "秦俑情散场→醉长安 41km 零车程必须报铁律 7"
    )
    assert not report.ok


def test_rule7_message_mentions_taxi_minutes():
    plan = _plan(_show(), _restaurant())
    report = validate_plan(plan, poi_hours=[])
    v = next(v for v in report.violations if v.rule_id == 7)
    need = travel_gap_needed(_show(), _restaurant())
    assert need is not None and need > 60
    assert str(need) in v.message


# --- ② travel_gap_needed：豁免面收窄 ----------------------------------


def test_gap_needed_far_food_pair_computed():
    need = travel_gap_needed(_show(), _restaurant())
    assert need == max(30, taxi_leg_min(_KM))  # 同口径 max(30, taxi)


def test_gap_needed_same_venue_food_pair_exempt():
    host = VisitItem(
        item_id="host",
        name="街区",
        city="西安",
        day=4,
        category="citywalk",
        duration_minutes=240,
        start_time=_t(17, 0),
        end_time=_t(21, 0),
        location=GeoPoint(lon=108.9426, lat=34.2611),
    )
    near_food = VisitItem(
        item_id="near-food",
        name="同址餐",
        city="西安",
        day=4,
        category="food",
        duration_minutes=90,
        start_time=_t(17, 30),
        end_time=_t(19, 0),
        location=GeoPoint(lon=108.9428, lat=34.2612),
    )
    assert travel_gap_needed(host, near_food) is None, "同址对免隔腿"


def test_gap_needed_locationless_pair_exempt():
    locless = VisitItem(
        item_id="no-loc",
        name="无坐标餐",
        city="西安",
        day=4,
        category="food",
        duration_minutes=60,
        start_time=_t(12, 20),
        end_time=_t(13, 20),
    )
    assert travel_gap_needed(_show(), locless) is None


# --- ③ 兜底排序：已排餐/酒店锚后落位须留腿 ---------------------------


def test_fallback_respects_leg_after_timed_lunch():
    lunch = VisitItem(
        item_id="lunch",
        name="午饭",
        city="西安",
        day=4,
        category="food",
        duration_minutes=90,
        pinned=True,  # 钉住才进固定窗（未钉午餐走 flex 通道不占窗）
        start_time=_t(12, 0),
        end_time=_t(13, 30),
        location=BINGMAYONG,
    )
    sight = VisitItem(
        item_id="sight",
        name="城心馆",
        city="西安",
        day=4,
        category="museum",
        best_visit_time="afternoon",  #  floor 12:00，强制探进午餐之后
        duration_minutes=120,
        location=ZHONGLou,
    )
    plan = _plan(lunch, sight)
    _fallback_sequence_times(plan)
    assert sight.start_time is not None, "未排点须落位"
    leg = taxi_leg_min(_KM)
    start_min = sight.start_time.hour * 60 + sight.start_time.minute
    assert start_min - (13 * 60 + 30) >= max(0, leg - 30), (
        f"餐锚后落位须留打车腿：散场 13:30 + {leg} 分钟腿，实际 {sight.start_time}"
    )


def test_fallback_respects_leg_after_hotel_card():
    hotel = VisitItem(
        item_id="hotel",
        name="入住卡",
        city="西安",
        day=4,
        category="hotel",
        duration_minutes=30,
        start_time=_t(11, 0),
        end_time=_t(11, 30),
        location=BINGMAYONG,
    )
    sight = VisitItem(
        item_id="sight",
        name="城心馆",
        city="西安",
        day=4,
        category="museum",
        best_visit_time="afternoon",  # floor 12:00，探进酒店锚之后
        duration_minutes=120,
        location=ZHONGLou,
    )
    plan = _plan(hotel, sight)
    _fallback_sequence_times(plan)
    assert sight.start_time is not None
    leg = taxi_leg_min(_KM)
    start_min = sight.start_time.hour * 60 + sight.start_time.minute
    assert start_min - (11 * 60 + 30) >= max(0, leg - 30), (
        f"酒店锚后落位须留打车腿：入住 11:30 + {leg} 分钟腿，"
        f"实际 {sight.start_time}（2026-11-13 全对象计腿拍板）"
    )


# --- ④ solver 插入主路：矩阵对餐/酒店 located 同口径 -----------------


def test_insertion_never_places_restaurant_within_leg_of_show():
    show = _show()
    restaurant = _restaurant()
    restaurant.start_time = None  # 未排，交给 solver
    restaurant.end_time = None
    day = DayPlan(day=4, base_city="西安", items=[show, restaurant])
    matrix = _travel_matrix(
        ItineraryPlan(
            itinerary_id="it-m",
            cities=["西安"],
            days=[day],
            assumptions=[],
        )
    )
    need = matrix[(show.item_id, restaurant.item_id)]
    assert need == max(30, taxi_leg_min(_KM)), "矩阵对餐对须 ≥30 地板同口径"
    solved = insertion_schedule_day(day, poi_hours=[], travel_minutes=matrix)
    assert solved is not None
    placed = next(i for i in solved.items if i.item_id == "food-zuichangan")
    assert placed.start_time is not None
    gap = placed.start_time.hour * 60 + placed.start_time.minute - (12 * 60 + 20)
    assert gap >= need, (
        f"餐厅 {placed.start_time} 开场，距散场仅 {gap} 分钟，"
        f"打车需 {need} 分钟——插入主路不得零车程贴脸"
    )
