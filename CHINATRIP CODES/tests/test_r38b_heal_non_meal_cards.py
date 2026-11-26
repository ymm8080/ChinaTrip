# -*- coding: utf-8 -*-
"""R38b（2026-11-25 用户「why pick 北京璞瑄酒店·大堂吧」的读路径收口）。

R38 只在选餐时把酒廊/大堂吧挡在 geo 池外，管的是**新生成**；已经落库的
会话刷新时仍把大堂吧当晚餐交付。R38b 在出站前把这类卡就地换成真餐馆。

覆盖：
1. 午餐卡=大堂吧 + 邻近真餐馆 → 换店，时刻/卡号不动，留披露；
2. 库里只有酒廊/低分店 → 原样保留（宁留卡也不塞不合格店）；
3. 真餐馆在 5km 外 → 不动（不为「看起来对」硬塞远店）；
4. 下午茶卡上的大堂吧 → 不动（大堂吧卖下午茶是合理安排）；
5. 幂等：换完再跑一次零改动；
6. 目标店已在行程里 → 跳过（不重复同一家）。
"""

from __future__ import annotations

from datetime import time
from types import SimpleNamespace

from app.services.agent.plan import heal_non_meal_meal_cards
from app.services.itinerary.models import DayPlan, GeoPoint, ItineraryPlan, VisitItem

ANKOR = (116.400, 39.900)


def _row(name, lon, lat, rating, **kw):
    row = {
        "name": name,
        "name_en": kw.get("name_en"),
        "city": "北京",
        "category": "food",
        "address": kw.get("address", "东城区某某街1号"),
        "address_en": None,
        "opening_hours": kw.get("opening_hours", "11:00-22:00"),
        "opening_hours_en": None,
        "source_poi_id": kw.get("poi_id", "r-%s" % name),
        "rating": rating,
        "rating_source": "ta",
        "cuisine": kw.get("cuisine"),
        "cuisine_group": kw.get("cuisine_group"),
        "location": (lon, lat),
        "suggested_duration_min": 60,
    }
    return row


class _Store:
    def __init__(self, rows):
        self._rows = rows

    def restaurant_rows_in_city(self, city):
        return list(self._rows)


def _food(iid, name, at, dur=60):
    h, m = (int(x) for x in at.split(":"))
    return VisitItem(
        item_id=iid,
        name=name,
        category="food",
        city="北京",
        poi_id="p1",
        start_time=time(h, m),
        end_time=time(h + 1, m),
        duration_minutes=dur,
        day=1,
    )


def _sight(iid, name, lon, lat, at="10:00"):
    h, m = (int(x) for x in at.split(":"))
    return VisitItem(
        item_id=iid,
        name=name,
        category="sight",
        city="北京",
        location=GeoPoint(lon=lon, lat=lat),
        start_time=time(h, m),
        end_time=time(h + 1, m),
        duration_minutes=60,
        day=1,
    )


def _session(*items):
    plan = ItineraryPlan(
        itinerary_id="t",
        cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=list(items))],
    )
    return SimpleNamespace(session_id="t", plan=plan)


def test_swaps_lounge_for_nearby_real_restaurant():
    s = _session(
        _sight("v1", "故宫", *ANKOR),
        _food("meal-lunch-1", "北京璞瑄酒店·大堂吧", "12:00"),
    )
    store = _Store(
        [
            _row("北京璞瑄酒店·大堂吧", 116.401, 39.901, 5.0),
            _row("南门涮肉(东单店)", 116.405, 39.902, 4.6),
        ]
    )
    notes = heal_non_meal_meal_cards(s, store=store)
    assert notes and "南门涮肉(东单店)" in notes[0]
    card = s.plan.days[0].items[1]
    assert card.name == "南门涮肉(东单店)"
    assert card.start_time == time(12, 0) and card.end_time == time(13, 0)
    assert card.item_id == "meal-lunch-1" and card.poi_id == "r-南门涮肉(东单店)"
    assert card.category == "food"
    assert any("非正餐" in a for a in s.plan.assumptions)


def test_keeps_card_when_pool_has_only_lounges_or_low_rating():
    s = _session(
        _sight("v1", "故宫", *ANKOR),
        _food("meal-dinner-1", "北京璞瑄酒店·大堂吧", "19:00"),
    )
    store = _Store(
        [
            _row("XX酒店行政酒廊", 116.401, 39.901, 4.8),
            _row("胡同小馆", 116.402, 39.902, 3.6),
        ]
    )
    assert heal_non_meal_meal_cards(s, store=store) == []
    assert s.plan.days[0].items[1].name == "北京璞瑄酒店·大堂吧"


def test_keeps_card_when_only_far_restaurant():
    s = _session(
        _sight("v1", "故宫", *ANKOR),
        _food("meal-dinner-1", "北京璞瑄酒店·大堂吧", "19:00"),
    )
    # 0.2 度经度 ≈ 17km，超出 2/5km 两档
    store = _Store([_row("远郊农家院", 116.600, 39.900, 4.9)])
    assert heal_non_meal_meal_cards(s, store=store) == []
    assert s.plan.days[0].items[1].name == "北京璞瑄酒店·大堂吧"


def test_tea_card_lounge_is_left_alone():
    s = _session(
        _sight("v1", "故宫", *ANKOR),
        _food("meal-tea-1", "北京璞瑄酒店·大堂吧", "15:30"),
    )
    store = _Store([_row("南门涮肉(东单店)", 116.405, 39.902, 4.6)])
    assert heal_non_meal_meal_cards(s, store=store) == []
    assert s.plan.days[0].items[1].name == "北京璞瑄酒店·大堂吧"


def test_idempotent_after_swap():
    s = _session(
        _sight("v1", "故宫", *ANKOR),
        _food("meal-lunch-1", "北京璞瑄酒店·大堂吧", "12:00"),
    )
    store = _Store([_row("南门涮肉(东单店)", 116.405, 39.902, 4.6)])
    assert len(heal_non_meal_meal_cards(s, store=store)) == 1
    assert heal_non_meal_meal_cards(s, store=store) == []


def test_skips_restaurant_already_in_plan():
    s = _session(
        _sight("v1", "故宫", *ANKOR),
        _food("meal-dinner-0", "南门涮肉(东单店)", "18:00"),
        _food("meal-lunch-1", "北京璞瑄酒店·大堂吧", "12:00"),
    )
    store = _Store([_row("南门涮肉(东单店)", 116.405, 39.902, 4.6)])
    assert heal_non_meal_meal_cards(s, store=store) == []
    assert s.plan.days[0].items[2].name == "北京璞瑄酒店·大堂吧"
