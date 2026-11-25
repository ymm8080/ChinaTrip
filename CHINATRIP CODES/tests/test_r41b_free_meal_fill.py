# -*- coding: utf-8 -*-
"""R41b：自由安排午/晚餐卡 → 就近推荐真餐厅（读路径自愈）。

用户 2026-11-25 复测「no restrant is recommended on the plan」+「keep（按写明
日程）也应该走 CP-SAT」：keep 盘每天被必去景点压满，引擎/legacy 都挤不出独立
餐块，餐卡留「午饭/晚饭（自由安排）」——本闸把占位卡的身份换成就近真餐馆
（打分与引擎同源：评分 × 评分数 × 距离），不动任何景点与时刻。
"""

from __future__ import annotations

from datetime import time
from types import SimpleNamespace

from app.services.agent.plan import heal_free_meal_cards
from app.services.itinerary.models import DayPlan, GeoPoint, ItineraryPlan, VisitItem


def _sight(item_id, name, lon, lat, start, dur=150):
    end = time(
        (start.hour * 60 + start.minute + dur) // 60 % 24, (start.minute + dur) % 60
    )
    return VisitItem(
        item_id=item_id,
        name=name,
        category="temple",
        city="北京",
        day=1,
        location=GeoPoint(lon=lon, lat=lat),
        start_time=start,
        end_time=end,
        duration_minutes=dur,
    )


def _placeholder(item_id, name, start, dur=60):
    end = time(
        (start.hour * 60 + start.minute + dur) // 60 % 24, (start.minute + dur) % 60
    )
    return VisitItem(
        item_id=item_id,
        name=name,
        category="food",
        city="北京",
        day=1,
        start_time=start,
        end_time=end,
        duration_minutes=dur,
    )


def _row(name, lon, lat, rating, count=None):
    return {
        "name": name,
        "category": "food",
        "location": (lon, lat),
        "rating": rating,
        "rating_count": count,
        "source_poi_id": "poi-" + name,
    }


class _Store:
    def __init__(self, rows):
        self._rows = list(rows)

    def restaurant_rows_in_city(self, city):
        return list(self._rows)


def _session(days):
    plan = ItineraryPlan(itinerary_id="it1", cities=["北京"], days=days)
    return SimpleNamespace(plan=plan, session_id="s1")


# 天坛 (116.4128, 39.8836)。1.11km 外的高评论数店 vs 1.9km 外的小样本满分店。
_ROWS = [
    _row("南门涮肉(天坛店)", 116.4120, 39.8840, 4.5, 106),
    _row("刘记炙子烤肉(虎坊桥店)", 116.4010, 39.8790, 4.8, 4),
    _row("远郊满分店", 117.2000, 40.3000, 5.0, 999),
]


def _day_one():
    return DayPlan(
        day=1,
        base_city="北京",
        items=[
            _sight("v1", "天坛", 116.4128, 39.8836, time(9, 0)),
            _placeholder("meal-lunch-1", "午餐", time(12, 10)),
            _placeholder("meal-dinner-1", "晚饭", time(18, 30)),
        ],
    )


def test_free_cards_fill_with_nearby_restaurants_by_score():
    session = _session([_day_one()])
    notes = heal_free_meal_cards(session, store=_Store(_ROWS))
    items = {i.item_id: i for i in session.plan.days[0].items}
    lunch = items["meal-lunch-1"]
    dinner = items["meal-dinner-1"]
    # 评分数把「5.0×1 条」压下去：午餐落 4.5×106 的天坛店
    assert lunch.name == "南门涮肉(天坛店)"
    assert lunch.location is not None and lunch.poi_id
    assert lunch.start_time == time(12, 10)  # 卡号/时刻不动
    # 晚餐拿第二家（同日不重复）
    assert dinner.name == "刘记炙子烤肉(虎坊桥店)"
    assert len(notes) == 2 and "南门涮肉" in notes[0]
    # 幂等：填完的卡不再是占位件
    assert heal_free_meal_cards(session, store=_Store(_ROWS)) == []


def test_card_outside_meal_window_is_left_alone():
    day = DayPlan(
        day=1,
        base_city="北京",
        items=[
            _sight("v1", "天坛", 116.4128, 39.8836, time(9, 0)),
            _placeholder("meal-lunch-1", "午餐", time(9, 30)),  # 早餐时段的「午餐」
        ],
    )
    session = _session([day])
    assert heal_free_meal_cards(session, store=_Store(_ROWS)) == []
    assert session.plan.days[0].items[1].name == "午餐"


def test_no_nearby_restaurant_leaves_placeholder():
    day = DayPlan(
        day=1,
        base_city="北京",
        items=[
            _sight("v1", "慕田峪长城", 116.5598, 40.4267, time(10, 0)),
            _placeholder("meal-dinner-1", "晚饭", time(18, 30)),
        ],
    )
    session = _session([day])
    assert heal_free_meal_cards(session, store=_Store(_ROWS)) == []
    assert session.plan.days[0].items[1].name == "晚饭"


def test_existing_named_meal_card_is_not_replaced():
    named = VisitItem(
        item_id="meal-dinner-2",
        name="四季民福烤鸭店（故宫店）",
        category="food",
        city="北京",
        day=1,
        start_time=time(18, 0),
        end_time=time(19, 0),
        duration_minutes=60,
    )
    day = DayPlan(
        day=1,
        base_city="北京",
        items=[_sight("v1", "天坛", 116.4128, 39.8836, time(9, 0)), named],
    )
    session = _session([day])
    assert heal_free_meal_cards(session, store=_Store(_ROWS)) == []
    assert session.plan.days[0].items[1].name == "四季民福烤鸭店（故宫店）"


def test_remote_day_early_lunch_is_filled():
    # 远郊日回城前的午餐开场 11:08：与引擎 R41 时段窗同口径（≥11:00）应填，
    # 不能再被 legacy 卡窗（11:30）挡掉。
    day = DayPlan(
        day=1,
        base_city="北京",
        items=[
            _placeholder("meal-lunch-3", "午餐", time(11, 8)),
            _sight("v8", "天坛", 116.4128, 39.8836, time(12, 8), dur=240),
        ],
    )
    session = _session([day])
    assert heal_free_meal_cards(session, store=_Store(_ROWS))
    assert session.plan.days[0].items[0].name == "南门涮肉(天坛店)"


def test_card_nested_inside_sight_block_is_left_free():
    # 卡整体嵌在景点块内（游览途中就地用餐）：同址语义，不塞 2km 外的店。
    day = DayPlan(
        day=1,
        base_city="北京",
        items=[
            _sight("v1", "天坛", 116.4128, 39.8836, time(9, 0), dur=240),
            _placeholder("meal-lunch-1", "午餐", time(12, 0)),
        ],
    )
    session = _session([day])
    assert heal_free_meal_cards(session, store=_Store(_ROWS)) == []
    assert session.plan.days[0].items[1].name == "午餐"
