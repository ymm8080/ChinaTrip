# -*- coding: utf-8 -*-
"""独立回城卡（2026-11-16 用户拍板「回程卡应该是独立卡」+「按时间排序」）。

口径：
1. 开始=游玩结束（同址午饭/晚饭占位卡在后时按其散场），有班次表就取最近的
   返程班次发车，无班次回落到上一段结束；
2. 结束=到市区落点；
3. 卡按时间排在当天时间轴里（回城 14:30 晚于午饭 14:08，必须排在午饭之后）；
4. 只在响应副本上生成——会话本体不落卡；景区卡留一行回城提示。
"""

from datetime import time

from app.api.plan import _plan_for_response
from app.services.itinerary import annotate_legs
from app.services.itinerary.legs import RETURN_CARD_PREFIX, attach_return_cards
from app.services.itinerary.models import DayPlan, GeoPoint, ItineraryPlan, VisitItem


def _v(item_id, name, lon, lat, **kw):
    base = dict(
        item_id=item_id,
        name=name,
        city="北京",
        day=1,
        duration_minutes=60,
        category="sight",
        location=GeoPoint(lon=lon, lat=lat),
        start_time=time(9, 0),
        end_time=time(10, 0),
    )
    base.update(kw)
    return VisitItem(**base)


def _remote_wall(**kw):
    base = dict(
        category="nature",
        duration_minutes=180,
        start_time=time(10, 8),
        end_time=time(13, 8),
        access_mode="shuttle",
        access_boarding=GeoPoint(lon=116.3982, lat=39.8988),
        access_service_name="前门旅游专线（前门大街北口）",
        access_boarding_stop="前门大街北口（北京旅游集散中心发车点）",
        access_alight_stop="慕田峪长城 P1/P4 停车场",
        access_service_minutes=90,
        access_wait_minutes=10,
        access_last_mile_minutes=8,
        access_return_times=["14:30", "15:30", "16:30"],
    )
    base.update(kw)
    return _v("mt", "慕田峪长城", 116.5598, 40.4267, **base)


def _placeholder(item_id, name, start, end, minutes=60):
    return VisitItem(
        item_id=item_id,
        name=name,
        category="food",
        city="北京",
        day=1,
        duration_minutes=minutes,
        anchor_from_prev=True,
        start_time=start,
        end_time=end,
    )


def _lunch():
    return _placeholder(
        "food-lunch-ph-d1", "午饭（自由安排）", time(13, 8), time(14, 8)
    )


def _night(start=time(21, 0), end=time(22, 0)):
    return VisitItem(
        item_id="hotel-night-d1",
        name="🏨 回酒店·夜间休息",
        category="hotel",
        city="北京",
        day=1,
        duration_minutes=60,
        start_time=start,
        end_time=end,
    )


def _plan(items):
    return ItineraryPlan(
        itinerary_id="x",
        cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=items)],
        assumptions=[],
    )


def test_return_card_is_separate_and_sorted_after_lunch():
    """回城 14:30 > 午饭 14:08：独立成卡并按时间排在午饭之后。"""
    mt = _remote_wall()
    plan = _plan(
        [
            mt,
            _lunch(),
            _placeholder(
                "food-dinner-ph-d1", "晚饭（自由安排）", time(19, 0), time(20, 30), 90
            ),
            _night(),
        ]
    )
    annotate_legs(plan)
    out = _plan_for_response(plan)
    ids = [i.item_id for i in out.days[0].items]

    card_id = f"{RETURN_CARD_PREFIX}mt"
    assert card_id in ids, ids
    card = next(i for i in out.days[0].items if i.item_id == card_id)
    # ① 开始=最近返程班次发车（午饭 14:08 散场 + 步行 8 → 14:16 → 14:30）
    assert card.start_time == time(14, 30)
    assert card.end_time == time(
        16, 8
    )  # ② 结束=到市区落点（R38 含下客步行，与卡面 arrive_city 同口径）
    assert card.synthetic is True
    assert card.category == "transfer"
    assert card.next_leg_detail is not None
    assert card.next_leg_detail["direction"] == "return"
    assert card.next_leg_detail["owner_item_id"] == "mt"
    # ③ 按时间排序：午饭之后、晚饭之前
    assert ids.index("food-lunch-ph-d1") < ids.index(card_id)
    assert ids.index(card_id) < ids.index("food-dinner-ph-d1")
    # ④ 景区卡清腿、只留一行回城提示
    site = next(i for i in out.days[0].items if i.item_id == "mt")
    # 明细留在卡上（下一轮装配据此重算，幂等），但摘要行清空、只留一行提示
    assert site.next_leg_detail and site.next_leg_detail["direction"] == "return"
    assert site.next_leg_minutes is None and site.distance_to_next_km is None
    hint = site.return_hint or ""
    assert "14:30" in hint and "前门大街北口" in hint
    # 会话本体不落卡
    assert len(plan.days[0].items) == 4
    assert all(
        not (i.item_id or "").startswith(RETURN_CARD_PREFIX) for i in plan.days[0].items
    )


def test_return_card_before_real_next_stop_of_day():
    """回城后还有真实下一站：卡插在景区/午饭之后、下一站之前。"""
    mt = _remote_wall()
    plan = _plan(
        [
            mt,
            _lunch(),
            _v(
                "tm",
                "天安门广场",
                116.4103,
                39.9115,
                start_time=time(16, 30),
                end_time=time(17, 30),
            ),
            _night(),
        ]
    )
    annotate_legs(plan)
    out = _plan_for_response(plan)
    ids = [i.item_id for i in out.days[0].items]
    card_id = f"{RETURN_CARD_PREFIX}mt"
    assert card_id in ids, ids
    assert ids.index("food-lunch-ph-d1") < ids.index(card_id) < ids.index("tm")
    card = next(i for i in out.days[0].items if i.item_id == card_id)
    assert card.start_time == time(14, 30)
    # 下一站是真实景点：明细里 next_stop 指它，游客知道自己被送到哪
    assert card.next_leg_detail["next_stop"] == "天安门广场"


def test_return_card_attach_is_idempotent():
    """重复装配只留一张卡（GET/编辑每次都会走出口）。"""
    plan = _plan(
        [
            _remote_wall(),
            _lunch(),
            _night(),
        ]
    )
    annotate_legs(plan)
    first = attach_return_cards(plan)
    second = attach_return_cards(first)
    cards = [
        i
        for i in second.days[0].items
        if (i.item_id or "").startswith(RETURN_CARD_PREFIX)
    ]
    assert len(cards) == 1
    assert cards[0].start_time == time(14, 30)
    # 提示行不重复叠加
    site = next(i for i in second.days[0].items if i.item_id == "mt")
    assert site.return_hint and site.return_hint.count("回城") == 1


# 2026-11-16 上海朱家角实报「从朱家角回去回程又没了」：末站是远郊点、没有班次
# 档案（地铁 17 号线/打车），后面只剩同址占位餐卡和没坐标的酒店卡——旧逻辑一条
# 腿都不出。这里按打车口径补「回城」段，出站投影成独立卡。


def _morning(anchor_lon=121.4737, anchor_lat=31.2304):
    return VisitItem(
        item_id="hotel-morning-d1",
        name="🏨 从酒店出发（今日起点）",
        category="hotel",
        city="上海",
        day=1,
        anchor_location=GeoPoint(lon=anchor_lon, lat=anchor_lat),
        start_time=time(10, 0),
        end_time=time(10, 30),
        duration_minutes=30,
        soft_pin=True,
    )


def _zhujiajiao():
    return VisitItem(
        item_id="v96",
        name="朱家角古镇",
        name_en="Zhujiajiao Ancient Town",
        category="attraction",
        city="上海",
        day=1,
        location=GeoPoint(lon=121.05052418499841, lat=31.11416165422822),
        start_time=time(11, 0),
        end_time=time(15, 0),
        duration_minutes=240,
    )


def _shanghai_plan(last_stop=None):
    items = [
        _morning(),
        last_stop or _zhujiajiao(),
        VisitItem(
            item_id="food-lunch-ph-d1",
            name="午饭（自由安排）",
            category="food",
            city="上海",
            day=1,
            anchor_from_prev=True,
            start_time=time(11, 30),
            end_time=time(12, 0),
            duration_minutes=30,
        ),
        VisitItem(
            item_id="food-dinner-ph-d1",
            name="晚饭（自由安排）",
            category="food",
            city="上海",
            day=1,
            anchor_from_prev=True,
            start_time=time(19, 0),
            end_time=time(20, 30),
            duration_minutes=90,
        ),
        VisitItem(
            item_id="hotel-night-d1",
            name="🏨 回酒店·夜间休息",
            category="hotel",
            city="上海",
            day=1,
            start_time=time(21, 0),
            end_time=time(22, 0),
            duration_minutes=60,
        ),
    ]
    return ItineraryPlan(
        itinerary_id="x",
        cities=["上海"],
        days=[DayPlan(day=1, base_city="上海", items=items)],
        assumptions=[],
    )


def test_plain_tail_return_when_last_stop_has_no_shuttle():
    """远郊末站没有班次档案：也要出「回城」卡（打车口径，不空着）。"""
    plan = _shanghai_plan()
    annotate_legs(plan)
    site = plan.days[0].items[1]
    detail = site.next_leg_detail
    assert detail is not None
    assert detail["direction"] == "return" and detail["to_city"] is True
    assert detail["mode"] == "taxi" and detail["service_name"] == ""
    assert detail["taxi_km"] > 40
    assert detail["depart_time"] == "15:00"
    assert site.next_leg_minutes == detail["taxi_minutes"]

    out = _plan_for_response(plan)
    ids = [i.item_id for i in out.days[0].items]
    card_id = f"{RETURN_CARD_PREFIX}v96"
    assert card_id in ids, ids
    card = next(i for i in out.days[0].items if i.item_id == card_id)
    assert "回城" in card.name
    assert card.start_time == time(15, 0)
    assert card.end_time == time(16, 2)
    assert ids.index(card_id) < ids.index("food-dinner-ph-d1")
    site_out = next(i for i in out.days[0].items if i.item_id == "v96")
    assert site_out.return_hint and "15:00" in site_out.return_hint
    # 晚饭不再留在景区停车场：回城后再吃
    dinner = next(i for i in out.days[0].items if i.item_id == "food-dinner-ph-d1")
    assert dinner.anchor_location is None and dinner.address is None


def test_no_plain_tail_return_for_city_stop():
    """市内末站（离锚点 2 km）不挂「回城」，免得每张末卡都多一行。"""
    near = _v(
        "bund",
        "外滩",
        121.4903,
        31.2414,
        start_time=time(17, 0),
        end_time=time(19, 0),
    )
    plan = _shanghai_plan(near)
    annotate_legs(plan)
    assert near.next_leg_detail is None
    out = _plan_for_response(plan)
    assert not [
        i for i in out.days[0].items if (i.item_id or "").startswith(RETURN_CARD_PREFIX)
    ]
