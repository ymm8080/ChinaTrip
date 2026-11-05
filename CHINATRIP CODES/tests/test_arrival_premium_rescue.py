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

from app.services.agent.plan import (
    _reconcile_transfer_days,
    _rehome_untimed_visits,
    _transfer_day_sweep,
)
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
_CQ = GeoPoint(lon=106.55, lat=29.56)  # 重庆渝中


def _visit(name, tier, *, minutes=90, loc=_CD, hours=None, pinned=False, city="成都"):
    return VisitItem(
        item_id=name,
        name=name,
        city=city,
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


# ---- 清算层让位救援（2026-11-05 成渝案三段）：兜底排序排不出 → 挪日
# 挪不动 → 旧路径整卡删除；现路径名点让位腾座 ----


def _timed(v, hh=9, mm=0):
    v.start_time = time(hh, mm)
    return v


def _tplan(day1_items, day2_items):
    d1 = DayPlan(day=1, base_city="上海", items=day1_items)
    d2 = DayPlan(day=2, base_city="成都", items=day2_items)
    for v in day2_items:
        v.day = 2
    return ItineraryPlan(itinerary_id="it2", cities=["上海", "成都"], days=[d1, d2])


_T2 = {
    "青城山—都江堰": 1,
    "金沙遗址博物馆": 11,
    "宽窄巷子": 8,
    "武侯祠": 9,
    "人民公园": 11,
    "洪崖洞": 8,
    "李子坝轻轨站": 9,
    "四面山": 8,
    # d2 档位显式化：金沙唯一最高档 → 弹座确定弹金沙（腾上午实位），
    # 其余压档避免码点序把青羊宫/望江楼顶成被弹者
    "望江楼公园": 10,
    "青羊宫": 10,
    "杜甫草堂": 9,
    "文殊院": 11,
}


def test_transfer_sweep_yields_for_premium():
    """转场日清算：王牌无宿主天 → 从同城满员日弹最低档腾座。

    宿主天实位探针终审（2026-11-05 洪崖洞案）：让位后探针须找到
    真实可排座（腿占段+16:30 开场闸+营业窗）才认宿主——被弹者
    （金沙 tier11 @9:00）腾出整个上午，其余点压到下午。"""
    premium = _premium(loc=_CD)  # 市区内点：腿窗不外扩，上午腾座即可排
    premium.day = 1
    day2 = [
        _timed(_visit("金沙遗址博物馆", 11, minutes=90), 9),
        _timed(_visit("宽窄巷子", 8, minutes=90), 13, 30),
        _timed(_visit("武侯祠", 9, minutes=90), 15),
        _timed(_visit("人民公园", 10, minutes=90), 16, 30),
    ]
    plan = _tplan([_arrival_leg(), premium], day2)
    notes = _transfer_day_sweep(plan, frozenset(), dict(_T2))
    d2_names = {i.name for i in plan.days[1].items}
    assert "青城山—都江堰" in d2_names
    moved = next(i for i in plan.days[1].items if i.name == "青城山—都江堰")
    assert moved.day == 2
    assert moved.start_time is None
    # 被弹者无宿主天（池内无同城日）→ 按口径移除留痕
    assert "金沙遗址博物馆" not in d2_names
    assert any("让位" in n for n in notes)


def test_transfer_sweep_non_premium_no_yield():
    """控制组：tier11 无时刻杂卡不触发让位，按原口径移除。"""
    stranded = _visit("金沙遗址博物馆", 11, minutes=180, hours="08:30-17:00")
    stranded.day = 1
    day2 = [
        _timed(_visit("宽窄巷子", 8, minutes=90)),
        _timed(_visit("武侯祠", 9, minutes=90), 10),
        _timed(_visit("人民公园", 11, minutes=90), 12),
        _timed(_visit("成都大熊猫繁育研究基地", 11, minutes=90, pinned=True), 14),
    ]
    plan = _tplan([_arrival_leg(), stranded], day2)
    notes = _transfer_day_sweep(plan, frozenset(), dict(_T2))
    assert "金沙遗址博物馆" not in _visit_names(plan)
    assert any("已从行程移除" in n for n in notes)
    assert not any("让位" in n for n in notes)


def test_rehome_sweep_yields_for_premium():
    """挪日扫尾：普通日满员收不下王牌 → 同城日让位腾座；被弹者
    满城无宿主 → 移除留痕。

    实位探针终审口径：d1（自家日）先试让位——文殊院腾座后探针仍
    被上午点 ±腿占段（成都→都江堰 ~56km 折 ~156min）挡死 → 原样
    还座换 d2；d2 弹金沙@9:00（tier11 最低）腾出上午实位（其余点
    ≥15:00，腿窗不回压上午）。"""
    stray = _premium()
    stray.day = 1
    day1 = [
        _timed(_visit("人民公园", 11, minutes=90)),
        _timed(_visit("宽窄巷子", 8, minutes=90), 10),
        _timed(_visit("武侯祠", 9, minutes=90), 12),
        _timed(_visit("文殊院", 11, minutes=90), 14),
        stray,
    ]
    day2 = [
        _timed(_visit("金沙遗址博物馆", 11, minutes=90), 9),
        _timed(_visit("望江楼公园", 11, minutes=90), 15),
        _timed(_visit("青羊宫", 11, minutes=90), 16, 30),
        _timed(_visit("杜甫草堂", 9, minutes=90), 18),
    ]
    d1 = DayPlan(day=1, base_city="成都", items=day1)
    d2 = DayPlan(day=2, base_city="成都", items=day2)
    for v in day2:
        v.day = 2
    plan = ItineraryPlan(itinerary_id="it3", cities=["成都"], days=[d1, d2])
    notes = _rehome_untimed_visits(plan, frozenset(), dict(_T2))
    d2_names = {i.name for i in plan.days[1].items}
    assert "青城山—都江堰" in d2_names
    # 被弹者（档位最低者）腾座后回填原日或他日——不静默消失
    assert any("让位" in n for n in notes)
    assert any("已改排第" in n or "无处可排" in n for n in notes)


def test_yield_gate_tier8_ejects_lower_prestige():
    """洪崖洞案：tier8 名点享让位权，弹出 tier9 杂点（李子坝级）；
    实位探针终审——弹武侯祠@9:00 腾出上午实座（其余点 ≥13:30）。"""
    hongya = _visit("洪崖洞", 8, minutes=90, loc=_CQ, city="重庆")
    hongya.day = 1
    d1 = DayPlan(day=1, base_city="重庆", items=[hongya])
    day2 = [
        _timed(_visit("武侯祠", 9, minutes=90, loc=_CQ, city="重庆"), 9),
        _timed(_visit("四面山", 8, minutes=90, loc=_CQ, city="重庆"), 13, 30),
        _timed(_visit("李子坝轻轨站", 9, minutes=90, loc=_CQ, city="重庆"), 15),
        _timed(_visit("宽窄巷子", 8, minutes=90, loc=_CQ, city="重庆"), 16, 30),
    ]
    d2 = DayPlan(day=2, base_city="重庆", items=day2)
    for v in day2:
        v.day = 2
    plan = ItineraryPlan(itinerary_id="it4", cities=["重庆"], days=[d1, d2])
    notes = _rehome_untimed_visits(plan, frozenset(), dict(_T2))
    d2_names = {i.name for i in plan.days[1].items}
    assert "洪崖洞" in d2_names
    assert any("让位" in n for n in notes)


def test_rehome_yields_before_bouncing_to_arrival_day():
    """E2E 案回放（2026-11-05 session ea3e8305）：王牌滞留第2天时纯
    挪日会「结构上成功」挪进第1天到达日（容量闸不识营业窗——12:00
    落地+180min 名点终排必死）。现口径名点先让位：同城日弹低档腾座，
    王牌留在自家日，被弹者改排他日。"""
    premium = _premium()
    premium.day = 2
    d1 = DayPlan(day=1, base_city="上海", items=[_arrival_leg()])
    day2 = [
        _timed(_visit("成都大熊猫繁育研究基地", 11, minutes=150, pinned=True), 8),
        _timed(_visit("宽窄巷子", 8, minutes=90), 14),
        premium,
    ]
    d2 = DayPlan(day=2, base_city="成都", items=day2)
    for v in day2:
        v.day = 2
    plan = ItineraryPlan(itinerary_id="it5", cities=["上海", "成都"], days=[d1, d2])
    notes = _rehome_untimed_visits(plan, frozenset(), dict(_T2))
    assert premium.day == 2  # 不被挪进到达日
    assert any("让位" in n for n in notes)
