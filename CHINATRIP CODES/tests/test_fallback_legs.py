# -*- coding: utf-8 -*-
"""兜底排时行程腿回归（2026-11-02 兵马俑 10:30 散场 → 11:00 钟楼事故）：

兜底顺序排时（_fallback_sequence_times）此前对已定位观光锚只加平 ±30
缓冲、完全无视车程——10:30 散场的兵马俑后 34km 外的钟楼被排到 11:00。
修复：已占窗带源条目（fs, fe, src），未排条目经 _leg_windows 视角按
打车腿（_taxi_leg_min）放宽观光锚缓冲；餐饮/酒店/落地腿保持原窗
（贴点/铁律 4 语义不变）。
"""

from datetime import time as _t

from app.services.agent.plan import (
    _fallback_sequence_times,
    _leg_windows,
    _taxi_leg_min,
)
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    VisitItem,
)
from app.services.itinerary.rules import haversine_km

# 兵马俑（真实库位 5a_296）与西安钟楼（manual_xian_zhonglou）
BMY_LOC = GeoPoint(lon=109.28197771833138, lat=34.386245632396616)
ZL_LOC = GeoPoint(lon=108.943, lat=34.2611)


def _bmy():
    return VisitItem(
        item_id="bmy",
        name="秦始皇兵马俑博物馆",
        city="西安",
        day=4,
        category="sight",
        duration_minutes=90,
        start_time=_t(9, 0),
        end_time=_t(10, 30),
        location=BMY_LOC,
    )


def _zhonglou():
    return VisitItem(
        item_id="zl",
        name="西安钟楼",
        city="西安",
        day=4,
        category="sight",
        duration_minutes=60,
        location=ZL_LOC,
    )


def _lunch():
    return VisitItem(
        item_id="lunch",
        name="海底捞火锅(博乐里店)",
        city="西安",
        day=4,
        category="food",
        duration_minutes=60,
        start_time=_t(12, 0),
        end_time=_t(13, 0),
        pinned=True,
        location=GeoPoint(lon=108.93687, lat=34.342677),
    )


def _show():
    return VisitItem(
        item_id="show",
        name="《梦回大唐》",
        city="西安",
        day=4,
        category="entertainment",
        best_visit_time="show",
        duration_minutes=80,
        start_time=_t(17, 30),
        end_time=_t(18, 50),
        location=GeoPoint(lon=108.94, lat=34.3411),
    )


def test_fallback_honors_taxi_leg_from_earlier_anchor():
    """事故形态复现：兵马俑 09:00-10:30 + 未排钟楼(34km 外) + 钉死
    午餐 12:00 + 晚场演出。钟楼起排不得早于 散场+打车腿。"""
    day = DayPlan(
        day=4, base_city="西安", items=[_bmy(), _zhonglou(), _lunch(), _show()]
    )
    plan = ItineraryPlan(
        itinerary_id="it-x", cities=["西安"], days=[day], assumptions=[]
    )
    _fallback_sequence_times(plan)
    zl = next(i for i in day.items if i.item_id == "zl")
    assert zl.start_time is not None, "钟楼应可落位（日 4 空档充足）"
    zl_start = zl.start_time.hour * 60 + zl.start_time.minute
    leg = _taxi_leg_min(haversine_km(BMY_LOC, ZL_LOC))
    assert leg >= 100, "兵马俑→西安钟楼打车腿应约 106 分钟"
    assert zl_start >= 10 * 60 + 30 + leg, (
        f"钟楼 {zl.start_time} 早于 散场10:30+腿{leg}分——兜底又无视车程"
    )


def test_fallback_cap_keeps_far_anchor_bounded_not_impossible():
    """防御纵深：即使带毒坐标（883km 跨城点）漏进来，兜底也按腿距
    上限 180 分钟拉开——不再产出背靠背不可能时刻。"""
    beijing_zl = _zhonglou()
    beijing_zl.location = GeoPoint(lon=116.413, lat=39.944)  # 北京钟楼毒坐标
    day = DayPlan(day=4, base_city="西安", items=[_bmy(), beijing_zl])
    plan = ItineraryPlan(
        itinerary_id="it-x", cities=["西安"], days=[day], assumptions=[]
    )
    _fallback_sequence_times(plan)
    assert beijing_zl.start_time is not None
    start = beijing_zl.start_time.hour * 60 + beijing_zl.start_time.minute
    assert start >= 10 * 60 + 30 + 180  # 触顶腿 180 分钟


def test_leg_windows_widens_sight_anchor_only():
    """_leg_windows 视角：观光锚按腿放宽（pad-30），餐饮/酒店/无源
    （落地腿）窗保持原样；src 是自身时也保持原样。"""
    sight = _bmy()
    meal = _lunch()
    far = _zhonglou()
    fixed = [
        (8 * 60 + 30, 11 * 60, sight),
        (12 * 60, 13 * 60, meal),
        (7 * 60, 7 * 60 + 30, None),
        (9 * 60, 10 * 60 + 30, far),
    ]
    view = _leg_windows(fixed, far)
    leg = _taxi_leg_min(haversine_km(BMY_LOC, ZL_LOC))
    assert view[0] == (8 * 60 + 30 - (leg - 30), 11 * 60 + (leg - 30))
    assert view[1] == (12 * 60, 13 * 60)  # 餐饮贴点不动
    assert view[2] == (7 * 60, 7 * 60 + 30)  # 落地腿缓冲不动
    assert view[3] == (9 * 60, 10 * 60 + 30)  # 自身窗不动
