# -*- coding: utf-8 -*-
"""端点日演出距离闸 + 远郊片区成族成日（2026-11-13 西安实弹两连）。

用户拍板：
① 「SITES OR SHOW OR LUNCH 都要在酒店/市中心 8 公里内」——到达日与离城日
   同口径（_EP_LIGHT_KM=8km，酒店优先、城心锚同核）。
② 「到达日把兵马俑删了，但是为什么不删秦俑情。这些远郊的景点应该成族后
   选单独日子安排」——远郊件（含演出）先由 _day_purity_sweep ③ 出圈片区
   族对齐收进同一个非端点日（族日），① 到达日闸随后空转；不再出现「兵马俑
   被单张删掉、秦俑情因演出豁免留在到达日」的一删一留。

本文件锚：
- 纯族对齐（无族演）也能成族日（旧代码族锚必须是「坐族内演出的日」）；
- 族演可从到达日并回族日；
- 端点日上无族可归的演出按 8km 闸挪走/移除，钉住只披露不挪。
"""

from datetime import time

from app.services.agent.plan import _day_purity_sweep, _endpoint_day_light_sweep
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    VisitItem,
)

# 城心簇（钟楼一带，5 点互距 ≤1km——medoid 稳定取城心，不被远郊点抢锚）
_C0 = GeoPoint(lon=108.9400, lat=34.2600)
_C1 = GeoPoint(lon=108.9410, lat=34.2605)
_C2 = GeoPoint(lon=108.9420, lat=34.2610)
_C3 = GeoPoint(lon=108.9430, lat=34.2615)
_C4 = GeoPoint(lon=108.9440, lat=34.2620)
# 临潼片区（兵马俑/华清宫/骊山/秦俑情，两两 ≤7km，距城心 ~30km）
_BMY = GeoPoint(lon=109.2730, lat=34.3840)  # 秦始皇帝陵博物院
_HQG = GeoPoint(lon=109.2150, lat=34.3589)  # 华清宫
_LSH = GeoPoint(lon=109.2130, lat=34.3729)  # 骊山
_QYQ = GeoPoint(lon=109.2809, lat=34.3804)  # 《秦俑情》
# 城心 8km 内的演出场地（合法端点日内容）
_NEAR_SHOW = GeoPoint(lon=108.9900, lat=34.2600)


def _v(
    name: str,
    dur: int,
    loc: GeoPoint | None,
    day: int,
    *,
    category: str = "sight",
    tier: int | None = None,
    pinned: bool = False,
    start: time | None = None,
) -> VisitItem:
    return VisitItem(
        item_id=f"v-{name}-{day}",
        name=name,
        city="西安",
        day=day,
        duration_minutes=dur,
        location=loc,
        category=category,
        tier=tier,
        pinned=pinned,
        start_time=start,
        end_time=None,
    )


def _show(name: str, day: int, loc: GeoPoint | None = _QYQ, **kw) -> VisitItem:
    return _v(name, 80, loc, day, category="entertainment", **kw)


def _d(day: int, *items) -> DayPlan:
    return DayPlan(day=day, base_city="西安", items=list(items))


def _plan(*days: DayPlan) -> ItineraryPlan:
    return ItineraryPlan(itinerary_id="it-ep-show", cities=["西安"], days=list(days))


def _day_of(plan: ItineraryPlan, v: VisitItem) -> int:
    for d in plan.days:
        if any(i is v for i in d.items):
            return d.day
    raise AssertionError(f"{v.name} 不在任何一天")


def _center_day(day: int, *coords: GeoPoint) -> DayPlan:
    return _d(
        day, *[_v(f"城件{day}{k}", 60, c, day, tier=9) for k, c in enumerate(coords)]
    )


def _tail(day: int) -> DayPlan:
    """末日=单城镜像返程日（只留一张近处轻街卡）。"""
    return _d(day, _v("尾坊", 90, _C4, day, tier=4))


def _run(plan: ItineraryPlan) -> None:
    _day_purity_sweep(plan, frozenset())
    _endpoint_day_light_sweep(plan, frozenset())


# ------------------------------------------------- 远郊族成日（用户拍板 ②）


def test_far_family_gets_own_day_arrival_far_items_not_dropped():
    """兵马俑+秦俑情在到达日 → 并回临潼族日（第 3 天），一张都不删。"""
    bmy = _v("秦始皇帝陵博物院", 180, _BMY, 1, tier=1)
    show = _show("《秦俑情》", 1)
    d1 = _d(1, bmy, show)
    d2 = _center_day(2, _C0, _C1, _C2, _C3)
    hqg = _v("华清宫", 90, _HQG, 3, tier=1)
    lsh = _v("骊山", 90, _LSH, 3, tier=9)
    d3 = _d(3, hqg, lsh)
    plan = _plan(d1, d2, d3, _tail(4))
    _run(plan)

    assert _day_of(plan, bmy) == 3, "兵马俑应并回远郊族日而不是被删"
    assert _day_of(plan, show) == 3, "族演应随族并回远郊族日"
    assert plan.unplaced == [], "远郊族对齐不得丢卡"
    assert any(
        "秦始皇帝陵博物院" in str(a) and "已合并至第3天" in str(a)
        for a in plan.assumptions
    )
    # 到达日不再留任何远郊件
    assert not any(_day_of(plan, i) == 1 for i in (bmy, show))
    # 全表排上时刻
    for d in plan.days:
        for i in d.items:
            assert i.start_time is not None, f"{i.name} 排不上时刻"


def test_far_family_without_show_also_forms_district_day():
    """无族演的纯片区族同样成族日（旧代码只认「坐族内演出的日」当锚）。"""
    bmy = _v("秦始皇帝陵博物院", 180, _BMY, 1, tier=1)
    d1 = _d(1, bmy)
    d2 = _center_day(2, _C0, _C1, _C2, _C3)
    hqg = _v("华清宫", 90, _HQG, 3, tier=1)
    lsh = _v("骊山", 90, _LSH, 3, tier=9)
    plan = _plan(d1, d2, _d(3, hqg, lsh), _tail(4))
    _run(plan)

    assert _day_of(plan, bmy) == 3
    assert plan.unplaced == []


# ------------------------------------------------- 端点日演出 8km 闸（拍板 ①）


def test_show_within_circle_stays_on_arrival_day():
    """酒店/市中心 8km 内的演出=合法端点内容，留原地不动。"""
    show = _show("《长安夜宴》", 1, loc=_NEAR_SHOW)
    d1 = _d(1, show)
    plan = _plan(d1, _center_day(2, _C0, _C1, _C2, _C3), _tail(3))
    _run(plan)

    assert _day_of(plan, show) == 1
    assert not any("长安夜宴" in str(a) for a in plan.assumptions)


def test_far_show_removed_to_unplaced_when_no_host():
    """无族可归、非端点日全满 → 移除落 unplaced（端点日绝不留 8km 外节目）。"""
    show = _show("《秦俑情》", 1)
    full = [
        _v("满员0", 60, _C0, 2, tier=9),
        _v("满员1", 60, _C1, 2, tier=9),
        _v("满员2", 60, _C2, 2, tier=9),
        _v("满员3", 60, _C3, 2, tier=9),
    ]
    plan = _plan(_d(1, show), _d(2, *full), _tail(3))
    _run(plan)

    assert all(not any(i is show for i in d.items) for d in plan.days), (
        "违例演出不得滞留端点日"
    )
    chip = next((u for u in plan.unplaced if (u.poi_id or u.name) == show.name), None)
    assert chip is not None and chip.reason == "endpoint_stay"
    assert any(
        "秦俑情" in str(a) and "已从行程移除" in str(a) for a in plan.assumptions
    )


def test_pinned_far_show_kept_with_disclosure():
    """钉住演出=铁律 19 用户权威：不挪不删，但必披露（端点日违例可见）。"""
    show = _show("《秦俑情》", 1, pinned=True)
    full = [
        _v("满员0", 60, _C0, 2, tier=9),
        _v("满员1", 60, _C1, 2, tier=9),
        _v("满员2", 60, _C2, 2, tier=9),
        _v("满员3", 60, _C3, 2, tier=9),
    ]
    plan = _plan(_d(1, show), _d(2, *full), _tail(3))
    _run(plan)

    assert _day_of(plan, show) == 1
    assert show.pinned is True
    assert any("秦俑情" in str(a) and "铁律 19" in str(a) for a in plan.assumptions)


def test_all_endpoint_days_keeps_show_and_discloses():
    """全窗皆端点日（2 天行程）：无其他天可挪=留原地+披露，绝不删空行程。"""
    show = _show("《秦俑情》", 1)
    d1 = _d(
        1,
        show,
        _v("城件A", 60, _C0, 1, tier=9),
        _v("城件B", 60, _C1, 1, tier=9),
        _v("城件C", 60, _C2, 1, tier=9),
    )
    d2 = _d(2, _v("城件D", 60, _C3, 2, tier=9))
    plan = _plan(d1, d2)
    _run(plan)

    assert _day_of(plan, show) == 1
    assert any("秦俑情" in str(a) and "暂保留" in str(a) for a in plan.assumptions)


def test_far_show_evicted_from_return_day():
    """离城日同口径：末日 8km 外演出挪去非端点日。"""
    a = _v("城件A", 90, _C0, 1, tier=4)
    b = _v("城件B", 60, _C1, 1, tier=9)
    c = _v("城件C", 60, _C2, 2, tier=9)
    show = _show("《秦俑情》", 3)
    plan = _plan(_d(1, a, b), _d(2, c), _d(3, show))
    _run(plan)

    assert _day_of(plan, show) == 2, "离城日的远郊演出必须挪走"
    assert any("秦俑情" in str(a) and "已挪至第2天" in str(a) for a in plan.assumptions)


def test_far_show_without_coordinates_not_blocked():
    """缺坐标=不可核即不拦（11-08 口径），不得把无坐标演出误删。"""
    show = _show("《无坐标演出》", 1, loc=None)
    plan = _plan(_d(1, show), _center_day(2, _C0, _C1, _C2), _tail(3))
    _run(plan)

    assert _day_of(plan, show) == 1


def test_full_district_day_yields_weak_member_for_premium():
    """族日满员时弱族员让位给王牌（2026-11-13 五拍：宁可让骊山落 chip，
    也不能把兵马俑从到达日删掉——「删强留弱」不许可）。"""
    bmy = _v("秦始皇帝陵博物院", 180, _BMY, 1, tier=1)
    d1 = _d(1, bmy)
    d2 = _center_day(2, _C0, _C1, _C2, _C3)
    hqg = _v("华清宫", 90, _HQG, 3, tier=1)
    lsh = _v("骊山", 180, _LSH, 3, tier=9)
    show = _show("《秦俑情》", 3)
    weak = _v("临潼博物馆", 60, _LSH, 3, tier=10)
    d3 = _d(3, hqg, lsh, show, weak)
    plan = _plan(d1, d2, d3, _tail(4))
    _run(plan)

    assert _day_of(plan, bmy) == 3, "王牌必须进族日"
    assert not any(i is weak for d in plan.days for i in d.items), (
        "最弱族员应为王牌让位（落 chip）"
    )
    chip = next((u for u in plan.unplaced if u.name == weak.name), None)
    assert chip is not None and chip.reason == "cap"
    assert any("临潼博物馆" in str(a) and "让位" in str(a) for a in plan.assumptions)
