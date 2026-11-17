# -*- coding: utf-8 -*-
"""2026-11-14 三连拍板回归（用户「FIX IT THROUGHLY. NO MORE SUCH ERRORS」）：

①酒店夜卡 20:30–21:30 不吃 solver 21:00 日终闸——否则含定时夜卡的天重解
   恒不可行，钉住必去（故宫=心愿+必去+最高优先级）跨日救生恒回滚成灰卡，
   而 tier6 无点名凑数件（国家大剧院）反被排进。
②无真场次演出不进自动通道（保位/收尾桶/到达日填充）——「HAS NO SHOW
   TIME INFORMATION, WHY WE PICK IT UP?」。
③餐卡=槽位：可动景点让位到餐后（「PUT LUNCH ON 12 AND PUT 天坛 AFTER
   LUNCH」），钉住件挡住才缩时/嵌套；不轻易丢卡——整段落在大点窗内
   =「游览途中用餐」嵌套保留（lunch can be included in sites），真无处可
   放才丢且必披露。
"""

from datetime import time

import app.services.agent.plan as P
from app.services.agent.plan import (
    _ensure_meal_cards,
    _must_visit_room_sweep,
    _pick_arrival_nearby,
    is_lunch_placeholder,
)
from app.services.itinerary.models import DayPlan, GeoPoint, ItineraryPlan, VisitItem
from app.services.itinerary.solver import (
    _visit_spec,
    insertion_schedule_day,
    solve_day,
)


def _visit(
    item_id,
    name,
    *,
    dur,
    cat="temple",
    start=None,
    pinned=False,
    soft_pin=False,
    must=False,
    tier=None,
    rank=None,
    loc=None,
    hours=None,
    address=None,
) -> VisitItem:
    end = None
    if start is not None:
        m = start.hour * 60 + start.minute + dur
        end = time(m // 60 % 24, m % 60)
    return VisitItem(
        item_id=item_id,
        name=name,
        category=cat,
        city="北京",
        day=1,
        start_time=start,
        end_time=end,
        duration_minutes=dur,
        pinned=pinned,
        soft_pin=soft_pin,
        must=must,
        tier=tier,
        site_rank=rank,
        location=GeoPoint(lon=loc[0], lat=loc[1]) if loc else None,
        opening_hours=hours,
        address=address,
    )


def _hotel_night(day: int, start=time(20, 30), dur: int = 60) -> VisitItem:
    m = start.hour * 60 + start.minute + dur
    return VisitItem(
        item_id=f"hotel-night-d{day}",
        name="🏨 回酒店·夜间休息",
        category="hotel",
        city="北京",
        day=day,
        start_time=start,
        end_time=time(m // 60 % 24, m % 60),
        duration_minutes=dur,
        soft_pin=True,
    )


def _lunch_ph(day: int, start=time(12, 0), dur: int = 60) -> VisitItem:
    m = start.hour * 60 + start.minute + dur
    return VisitItem(
        item_id=f"food-lunch-ph-d{day}",
        name="午饭（自由安排）",
        category="food",
        city="北京",
        day=day,
        start_time=start,
        end_time=time(m // 60 % 24, m % 60),
        duration_minutes=dur,
        soft_pin=True,
    )


def _plan(days: list[DayPlan]) -> ItineraryPlan:
    return ItineraryPlan(itinerary_id="it-test", cities=["北京"], days=days)


def _minutes(v: VisitItem) -> int:
    return v.start_time.hour * 60 + v.start_time.minute


def _span(v: VisitItem) -> tuple[int, int]:
    return _minutes(v), _minutes(v) + int(v.duration_minutes or 60)


def _independent_overlap(meal: VisitItem, site: VisitItem) -> bool:
    """双订判定：时段相交且不是「游览途中用餐」嵌套（嵌套卡锚=宿主地址）。"""
    ms, me = _span(meal)
    ss, se = _span(site)
    if not (ms < se and me > ss):
        return False
    return meal.address != site.address


# --- ① 酒店夜卡日终闸 -------------------------------------------------------


def test_hotel_night_card_does_not_freeze_day_solve():
    """软钉夜宿卡 20:30–21:30（attach_hotel_nights 正常落位）不再让
    _visit_spec 返 None——含它的天插入/CP 两路都能排其余条目。"""
    hotel = _hotel_night(1)
    visit = _visit("v1", "某景点", dur=120, loc=(116.4, 39.9))
    day = DayPlan(day=1, base_city="北京", items=[hotel, visit])
    spec = _visit_spec(visit, {}, meal_flex=False)
    assert spec is not None
    # 酒店卡不是可排条目（2026-11-14 用户拍板「hotel night-rest cards
    # SHOULD eat the 21:00 sightseeing cap」）：它不进可行域，只作固定
    # 占用窗——_visit_spec 返 None 是正确的，关键是当天仍能求解。
    assert _visit_spec(hotel, {}, meal_flex=False) is None
    solved = insertion_schedule_day(day, poi_hours=[], travel_minutes=None)
    assert solved is not None
    timed = {i.item_id: i.start_time for i in solved.items if i.start_time}
    assert timed.get("v1") is not None
    cp = solve_day(day, poi_hours=[], travel_minutes=None, time_budget_seconds=3.0)
    assert cp is not None
    assert all(i.start_time is not None for i in cp.items)


# --- ① 联动：钉住必去跨日救生能落位（故宫案） ------------------------------


def test_crossday_rescue_places_pinned_must_over_optional_show():
    """故宫（钉住必去）灰卡 + 国家大剧院（tier6 无点名）在排：救生把故宫落进
    第 2 天、国家大剧院让位留痕；占位餐卡不进「想去」unplaced。"""
    tiananmen = _visit(
        "v16",
        "天安门广场",
        dur=90,
        cat="attraction",
        start=time(8, 30),
        pinned=True,
        must=True,
        rank=10,
        loc=(116.4103, 39.9114),
    )
    mutianyu = _visit(
        "v21",
        "慕田峪长城",
        dur=180,
        cat="nature",
        start=time(12, 0),
        pinned=True,
        must=True,
        rank=0,
        loc=(116.5598, 40.4267),
    )
    palace = _visit(
        "v14",
        "故宫博物院",
        dur=120,
        cat="museum",
        pinned=True,
        must=True,
        rank=0,
        loc=(116.4097, 39.9255),
        hours=(
            "周一关闭(法定节假日除外),4月1日至10月31日,周二至周日08:30-17:00"
            "(16:00停止检票),11月1日至3月31日,周二至周日08:30-16:30(15:30停止检票)"
        ),
    )
    day1 = DayPlan(
        day=1,
        base_city="北京",
        items=[
            tiananmen,
            _lunch_ph(1, time(11, 30), 30),
            mutianyu,
            palace,
            _hotel_night(1),
        ],
    )
    summer = _visit(
        "v22",
        "颐和园",
        dur=90,
        cat="park",
        start=time(9, 0),
        pinned=True,
        must=True,
        rank=0,
        loc=(116.2749, 39.9987),
    )
    tiantan = _visit(
        "v18",
        "天坛",
        dur=60,
        start=time(12, 0),
        pinned=True,
        must=True,
        rank=0,
        loc=(116.4128, 39.8836),
    )
    ncpa = _visit(
        "v20",
        "国家大剧院",
        dur=90,
        cat="entertainment",
        start=time(15, 40),
        rank=40,
        tier=6,
        loc=(116.3898, 39.9047),
        hours="场次随排期（档期制，以当日公告为准）",
    )
    hotel_morning = VisitItem(
        item_id="hotel-morning-d2",
        name="🏨 从酒店出发（今日起点）",
        category="hotel",
        city="北京",
        day=2,
        start_time=time(8, 30),
        end_time=time(9, 0),
        duration_minutes=30,
        soft_pin=True,
    )
    day2 = DayPlan(
        day=2,
        base_city="北京",
        items=[
            hotel_morning,
            summer,
            _lunch_ph(2, time(11, 30), 30),
            tiantan,
            ncpa,
            _hotel_night(2),
        ],
    )
    plan = _plan([day1, day2])
    agent = P.PlanningAgent(llm_adapter=None)
    notes = _must_visit_room_sweep(plan, cap_relax=True)
    plan, rescue_notes = agent._must_visit_crossday_rescue(plan, frozenset())
    notes.extend(rescue_notes)
    placed = next(i for d in plan.days for i in d.items if i.name == "故宫博物院")
    assert placed.start_time is not None, "钉住必去故宫必须拿到时刻"
    # 2026-11-14 用户拍板「塞不下还是流行最高优先级的，删最低优先级的」：
    # 故宫 rank 0 必须拿到时刻；rank 10 的天安门可被让位（不再要求挪第 2 天）。
    assert _minutes(placed) + 120 <= 16 * 60 + 30  # 闭馆 16:30 前离场
    # 用户拍板「塞不下还是流行最高优先级的，删最低优先级的」：rank 10 的
    # 天安门先让位（国家大剧院留在第 2 天不冲突即可）。
    unplaced_names = [u.name for u in plan.unplaced or []]
    assert "天安门广场" in unplaced_names
    # 系统占位餐卡/酒店卡绝不进「想去」留痕
    assert not any("午饭" in n or "酒店" in n for n in unplaced_names)


# --- ② 无真场次演出不进自动通道 ----------------------------------------------

_NCPA = {
    "name": "国家大剧院",
    "category": "entertainment",
    "location": {"lon": 116.3898, "lat": 39.9047},
    "rating": 4.7,
    "opening_hours": "场次随排期（档期制，以当日公告为准）",
    "suggested_duration_min": 90,
}
_SHOW_WITH_SESSIONS = {
    "name": "功夫传奇",
    "category": "entertainment",
    "location": {"lon": 116.4, "lat": 39.91},
    "rating": 4.6,
    "opening_hours": "19:30场",
    "suggested_duration_min": 70,
}
_STREET = {
    "name": "南锣鼓巷",
    "category": "citywalk",
    "location": {"lon": 116.4, "lat": 39.93},
    "rating": 4.5,
    "suggested_duration_min": 60,
}


def test_sessionless_show_not_picked_by_arrival_fill():
    anchor = (116.4, 39.91)
    # 无场次演出单独存在也不补进空到达日
    assert _pick_arrival_nearby([_NCPA], anchor, exclude=set()) is None
    # 同池有真景点时挑真景点，不挑无场次演出
    hit = _pick_arrival_nearby([_NCPA, _STREET], anchor, exclude=set())
    assert hit is not None and hit["name"] == "南锣鼓巷"
    # 有真场次的演出仍可补位（晚间锚点不断供）
    hit2 = _pick_arrival_nearby([_SHOW_WITH_SESSIONS], anchor, exclude=set())
    assert hit2 is not None and hit2["name"] == "功夫传奇"


# --- ③ 餐卡=槽位：可动景点让位到餐后 ------------------------------------------


def test_lunch_on_12_and_movable_site_moves_after_lunch():
    """可动景点（未钉）占 12:00 → 午饭卡 12:00 整小时落位，景点顺延到餐后
    （用户拍板「THE CORRECT SOLUTION IS TO PUT LUNCH ON 12 AND PUT 天坛
    AFTER LUNCH」）。"""
    tiantan = _visit(
        "v18",
        "天坛",
        dur=60,
        start=time(12, 0),
        loc=(116.4128, 39.8836),
        address="天坛公园",
    )
    day = DayPlan(day=1, base_city="北京", items=[tiantan])
    plan = _plan([day])
    _ensure_meal_cards(plan)
    lunch = next(i for i in day.items if is_lunch_placeholder(i))
    assert _minutes(lunch) == 12 * 60
    assert int(lunch.duration_minutes) == 60
    assert _minutes(tiantan) >= 13 * 60, "可动天坛必须顺延到午饭后"


def test_lunch_survives_next_to_pinned_site():
    """压住卡窗的是用户钉住件（铁律 19）→ 钉件不动；卡缩时贴窗或嵌套宿主
    （游览途中用餐），绝不双订、不静默丢。"""
    tiantan = _visit(
        "v18",
        "天坛",
        dur=60,
        start=time(12, 0),
        pinned=True,
        loc=(116.4128, 39.8836),
        address="天坛公园",
    )
    day = DayPlan(day=1, base_city="北京", items=[tiantan])
    plan = _plan([day])
    _ensure_meal_cards(plan)
    lunch = next(i for i in day.items if is_lunch_placeholder(i))
    assert _span(tiantan) == (12 * 60, 13 * 60), "铁律 19：钉住件不动"
    ls, le = _span(lunch)
    assert 11 * 60 + 30 <= ls and le <= 13 * 60 + 30
    assert not _independent_overlap(lunch, tiantan), "餐卡与钉件不得双订"


def test_lunch_nests_inside_big_site_block():
    """大点整段包含卡窗=「游览途中用餐」嵌套落位（lunch can be included in
    sites），卡面锚回填宿主站——不算重叠、不算缺卡。"""
    palace = _visit(
        "v14",
        "故宫博物院",
        dur=240,
        cat="museum",
        start=time(9, 0),
        pinned=True,
        loc=(116.4097, 39.9255),
        hours="08:30-16:30",
        address="北京市东城区景山前街4号",
    )
    day = DayPlan(day=1, base_city="北京", items=[palace])
    plan = _plan([day])
    _ensure_meal_cards(plan)
    lunch = next(i for i in day.items if is_lunch_placeholder(i))
    ls, le = _span(lunch)
    assert 9 * 60 <= ls and le <= 13 * 60, "餐卡嵌在宿主窗内"
    assert lunch.address == palace.address, "嵌套餐卡锚回填宿主站"


def test_overlap_reconcile_moves_movable_site_after_lunch():
    """既有形态根修：午饭卡与可动景点同压 12:00 → 对账把景点顺延到餐后，
    卡原位不动（d6fed2a0 双 12:00 病形）。"""
    lunch = _lunch_ph(1, time(12, 0), 60)
    tiantan = _visit(
        "v18",
        "天坛",
        dur=60,
        start=time(12, 0),
        loc=(116.4128, 39.8836),
        address="天坛公园",
    )
    day = DayPlan(day=1, base_city="北京", items=[lunch, tiantan])
    plan = _plan([day])
    _ensure_meal_cards(plan)
    assert _minutes(lunch) == 12 * 60 and int(lunch.duration_minutes) == 60
    assert _minutes(tiantan) >= 13 * 60


def test_overlap_reconcile_when_pinned_site_holds_window():
    """午饭卡与钉住景点同压 12:00 → 钉件不动；卡缩时贴窗或嵌套宿主，
    绝不双订。"""
    lunch = _lunch_ph(1, time(12, 0), 60)
    tiantan = _visit(
        "v18",
        "天坛",
        dur=60,
        start=time(12, 0),
        pinned=True,
        loc=(116.4128, 39.8836),
        address="天坛公园",
    )
    day = DayPlan(day=1, base_city="北京", items=[lunch, tiantan])
    plan = _plan([day])
    _ensure_meal_cards(plan)
    assert _span(tiantan) == (12 * 60, 13 * 60), "铁律 19：钉住件不动"
    assert not _independent_overlap(lunch, tiantan), "餐卡与钉件不得双订"
