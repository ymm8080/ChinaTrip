# -*- coding: utf-8 -*-
"""2026-11-05 成都青城山—都江堰被整卡删除回归（到达日搁浅王牌救援）：

1. tier1 王牌在到达日装不下（12:00 落地 + 150min 地板 = 14:30 起，
   180min 收 17:30 > 17:00 闭馆），次日 4 件满员无宿主天——旧路径
   整卡删除世遗；现路径从次日弹出最低档非钉参访（金沙 tier11）
   让位，王牌挪入次日；让位者无宿主天按原口径移除留痕。
2. 控制组：非王牌（tier11）搁浅仍走原删除口径，不让座。
3. 让座后仍进不去（同日互远闸挡宿主天）→ 被弹者还回原天，
   王牌按原口径移除——弹座不能造成二次破坏。
"""

from __future__ import annotations

from datetime import time

from app.services.agent.plan import _reconcile_transfer_days
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    TransferItem,
    VisitItem,
)

_CD = GeoPoint(lon=104.06, lat=30.66)  # 成都市区
_DJY = GeoPoint(lon=103.62, lat=31.00)  # 都江堰（距成都 ~48km）
_KD = GeoPoint(lon=102.22, lat=30.05)  # 康定（距都江堰 ~168km，互远）


def _visit(name, tier, *, minutes=90, loc=_CD, hours=None, pinned=False):
    return VisitItem(
        item_id=name,
        name=name,
        city="成都",
        day=1,
        duration_minutes=minutes,
        tier=tier,
        pinned=pinned,
        category="sight",
        location=loc,
        poi_id=f"poi_{name}",
        opening_hours=hours,
    )


def _premium(hours="08:30-17:00", loc=_DJY):
    v = _visit("青城山—都江堰", 1, minutes=180, loc=loc, hours=hours)
    v.day = 1
    return v


def _plan(day1_items, day2_items):
    day1 = DayPlan(day=1, base_city="成都", items=day1_items)
    day2 = DayPlan(day=2, base_city="成都", items=day2_items)
    for v in day2_items:
        v.day = 2
    return ItineraryPlan(itinerary_id="it1", cities=["上海", "成都"], days=[day1, day2])


def _arrival_leg():
    return TransferItem(
        item_id="t1",
        day=1,
        seq=1,
        mode="train",
        from_city="上海",
        to_city="成都",
        start_time=time(8, 0),
        end_time=time(12, 0),
    )


def _visit_names(plan: ItineraryPlan) -> set[str]:
    return {i.name for d in plan.days for i in d.items if isinstance(i, VisitItem)}


_TIERS = {
    "青城山—都江堰": 1,
    "金沙遗址博物馆": 11,
    "宽窄巷子": 8,
    "武侯祠": 9,
    "成都大熊猫繁育研究基地": 11,
}


def test_premium_rescued_eject_yields_slot():
    """王牌挪入满员次日，最低档非钉参访让位且无处可排被移除。"""
    day2 = [
        _visit("金沙遗址博物馆", 11, minutes=120),
        _visit("宽窄巷子", 8),
        _visit("武侯祠", 9),
        _visit("成都大熊猫繁育研究基地", 11, minutes=120, pinned=True),
    ]
    plan = _plan([_arrival_leg(), _premium()], day2)
    notes = _reconcile_transfer_days(plan, tier_by_name=dict(_TIERS))
    names_d2 = {i.name for i in plan.days[1].items}
    assert "青城山—都江堰" in names_d2
    moved = next(i for i in plan.days[1].items if i.name == "青城山—都江堰")
    assert moved.day == 2
    assert moved.start_time is None
    all_names = _visit_names(plan)
    assert "金沙遗址博物馆" not in all_names  # 让位后无宿主天 → 移除留痕
    assert any("让位" in n for n in notes)


def test_non_premium_stranded_still_removed():
    """控制组：tier11 搁浅点不触发让座，按原口径删除。"""
    day2 = [
        _visit("宽窄巷子", 8),
        _visit("武侯祠", 9),
        _visit("人民公园", 11),
        _visit("成都大熊猫繁育研究基地", 11, minutes=120, pinned=True),
    ]
    stranded = _visit("金沙遗址博物馆", 11, minutes=180, hours="08:30-17:00")
    plan = _plan([_arrival_leg(), stranded], day2)
    notes = _reconcile_transfer_days(plan, tier_by_name=dict(_TIERS))
    all_names = _visit_names(plan)
    assert "金沙遗址博物馆" not in all_names
    assert any("已从行程移除" in n for n in notes)
    assert {i.name for i in plan.days[1].items} == {
        "宽窄巷子",
        "武侯祠",
        "人民公园",
        "成都大熊猫繁育研究基地",
    }


def test_eject_restored_when_premium_still_cannot_host():
    """让座后王牌仍被互远闸挡住 → 被弹者还回原天，王牌照旧移除。"""
    day2 = [
        _visit("金沙遗址博物馆", 11, minutes=120),
        _visit("宽窄巷子", 8, loc=_KD),  # 与王牌互远 → 宿主天被闸
        _visit("武侯祠", 9),
        _visit("成都大熊猫繁育研究基地", 11, minutes=120, pinned=True),
    ]
    plan = _plan([_arrival_leg(), _premium()], day2)
    notes = _reconcile_transfer_days(plan, tier_by_name=dict(_TIERS))
    all_names = _visit_names(plan)
    # 王牌没救成（原口径移除），被弹者原样留在次日
    assert "青城山—都江堰" not in all_names
    d2_names = {i.name for i in plan.days[1].items if isinstance(i, VisitItem)}
    assert "金沙遗址博物馆" in d2_names
    assert any("已从行程移除" in n for n in notes)
    assert not any("让位" in n for n in notes)
