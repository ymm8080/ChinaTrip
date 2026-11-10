# -*- coding: utf-8 -*-
"""闭合行程（同城往返，上海→西安→上海）簇不拆天/王牌不落返程日锚
（2026-11-08 沪→西→沪案）。

用户案：D2-D4 被转场日压缩后——大雁塔↔十二时辰、城墙·碑林↔碑林博
拆天；兵马俑（tier1 王牌）被 first-fit 挪日塞进 D5 返程日上午（17:00
返沪航班前）。三锚：
① _day_has_departure 认离城腿（到达腿不算）；
② _host_day_for_visit 返程日殿后——有非返程宿主绝不首选返程日；
③ 返程日仍可作最后归宿（轻量件合法，离城上午闸口径不破）。
"""

from datetime import time

from app.services.agent.plan import _day_has_departure, _host_day_for_visit
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    TransferItem,
    VisitItem,
)

_BL = GeoPoint(lon=108.9397, lat=34.2565)  # 碑林（城心簇）


def _visit(name: str, dur: int, loc: GeoPoint | None, day: int = 1) -> VisitItem:
    return VisitItem(
        item_id=f"v-{name}",
        name=name,
        city="西安",
        day=day,
        duration_minutes=dur,
        location=loc,
    )


def _return_day(day_no: int = 5) -> DayPlan:
    """D5 返程日：17:00 西安→上海 航班。"""
    return DayPlan(
        day=day_no,
        base_city="西安",
        items=[
            TransferItem(
                item_id="t-ret",
                day=day_no,
                seq=1,
                from_city="西安",
                to_city="上海",
                mode="flight",
                start_time=time(17, 0),
                end_time=time(19, 30),
            )
        ],
    )


def test_day_has_departure_recognizes_leaving_leg_only():
    dep = _return_day()
    arr = DayPlan(
        day=1,
        base_city="上海",
        items=[
            TransferItem(
                item_id="t-arr",
                day=1,
                seq=1,
                from_city="上海",
                to_city="西安",
                mode="flight",
                start_time=time(9, 0),
                end_time=time(12, 0),
            )
        ],
    )
    plain = DayPlan(day=2, base_city="西安", items=[])
    assert _day_has_departure(dep, "西安") is True
    assert _day_has_departure(dep, "上海") is False  # 只认自该城离城
    assert _day_has_departure(arr, "西安") is False  # 到达腿不是返程日信号
    assert _day_has_departure(plain, "西安") is False


def test_host_day_prefers_non_departure_day_for_big_visit():
    """兵马俑 D5 案锚：返程日排探查序末位——空荡的 D5 不得抢在可用的
    非返程日前收 180min 大点。"""
    d4 = DayPlan(day=4, base_city="西安", items=[_visit("骊山", 120, _BL, day=4)])
    d5 = _return_day()
    host = _host_day_for_visit(
        [d5, d4], "西安", 180, incoming=_BL, visit=_visit("兵马俑", 180, _BL)
    )
    assert host is d4


def test_host_day_departure_day_usable_as_last_resort():
    """返程日不硬拦：无非返程宿主时轻量件仍可落（离城上午闸合法件）。"""
    d5 = _return_day()
    host = _host_day_for_visit(
        [d5], "西安", 60, incoming=_BL, visit=_visit("永兴坊", 60, _BL)
    )
    assert host is d5


def test_host_day_rejects_heavy_single_city_return_day():
    d4 = DayPlan(day=4, base_city="西安", items=[])
    d5 = DayPlan(day=5, base_city="西安", items=[])
    heavy = _visit("高优先级小点", 60, _BL)
    heavy.tier = 1
    host = _host_day_for_visit(
        [d5],
        "西安",
        60,
        incoming=_BL,
        visit=heavy,
        all_days=[d4, d5],
    )
    assert host is None

    light = _visit("普通轻量小点", 60, _BL)
    assert (
        _host_day_for_visit(
            [d5],
            "西安",
            60,
            incoming=_BL,
            visit=light,
            all_days=[d4, d5],
        )
        is d5
    )


# --- 2026-11-08 钟楼案三拍：楔子不变量（贴邻孤岛清障） ------------------------


def test_wedge_stray_evicted_when_mates_majority_elsewhere():
    """钟楼楔进大雁塔日实录：D2=大雁塔(>2km 远核心)+钟楼，钟楼贴邻伴
    （鼓楼/碑林馆）多数在 D3——清障移除并披露；D3 原样不动。"""
    from app.services.agent.plan import _evict_wedge_strays
    from app.services.itinerary.models import ItineraryPlan

    zl = GeoPoint(lon=108.9430, lat=34.2611)  # 钟楼
    gl = GeoPoint(lon=108.9432, lat=34.2608)  # 鼓楼 ~40m
    blg = GeoPoint(lon=108.9402, lat=34.2544)  # 碑林馆 ~0.9km
    dyt = GeoPoint(lon=108.9644, lat=34.2185)  # 大雁塔 ~6km 远核心

    d2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            _visit("大雁塔", 180, dyt, day=2),
            _visit("西安钟楼", 40, zl, day=2),
        ],
    )
    d3 = DayPlan(
        day=3,
        base_city="西安",
        items=[
            _visit("西安鼓楼", 40, gl, day=3),
            _visit("西安碑林博物馆", 90, blg, day=3),
        ],
    )
    plan = ItineraryPlan(itinerary_id="it-wedge", cities=["西安"], days=[d2, d3])
    dropped = _evict_wedge_strays(plan)
    assert dropped == ["西安钟楼"]
    assert [i.name for i in d2.items if isinstance(i, VisitItem)] == ["大雁塔"]
    assert {i.name for i in d3.items if isinstance(i, VisitItem)} == {
        "西安鼓楼",
        "西安碑林博物馆",
    }
    assert any("近邻多在第3天" in a for a in plan.assumptions)


def test_wedge_subgroup_same_day_not_evicted():
    """东方明珠四拍「不追改」边界：簇拆两日、散组同日互伴（本日伴数
    不弱于他日）且本日无 >2km 远核心——不是楔子，不动。"""
    from app.services.agent.plan import _evict_wedge_strays
    from app.services.itinerary.models import ItineraryPlan

    mz = GeoPoint(lon=121.4998, lat=31.2397)  # 东方明珠
    hy = GeoPoint(lon=121.5020, lat=31.2380)  # 海洋馆
    bj = GeoPoint(lon=121.5060, lat=31.2385)  # 滨江大道（与海洋馆互伴）

    d1 = DayPlan(day=1, base_city="上海", items=[_visit("东方明珠", 180, mz, day=1)])
    d2 = DayPlan(
        day=2,
        base_city="上海",
        items=[
            _visit("海洋馆", 120, hy, day=2),
            _visit("滨江大道", 90, bj, day=2),
        ],
    )
    plan = ItineraryPlan(itinerary_id="it-split", cities=["上海"], days=[d1, d2])
    assert _evict_wedge_strays(plan) == []
    assert {i.name for i in d2.items if isinstance(i, VisitItem)} == {
        "海洋馆",
        "滨江大道",
    }


def test_wedge_same_day_mates_keep_visit():
    """兵马俑+秦俑情同日互伴（本日伴=最多）不动——常态簇日全员免扫。"""
    from app.services.agent.plan import _evict_wedge_strays
    from app.services.itinerary.models import ItineraryPlan

    bmy = GeoPoint(lon=109.2785, lat=34.3834)
    qyq = GeoPoint(lon=109.2790, lat=34.3830)
    hqg = GeoPoint(lon=109.2120, lat=34.3620)  # 华清宫 ~6km 远核心

    d4 = DayPlan(
        day=4,
        base_city="西安",
        items=[
            _visit("秦始皇帝陵博物院", 180, bmy, day=4),
            _visit("《秦俑情》", 90, qyq, day=4),
            _visit("华清宫", 120, hqg, day=4),
        ],
    )
    d2 = DayPlan(
        day=2,
        base_city="西安",
        items=[_visit("大雁塔", 180, GeoPoint(lon=108.9644, lat=34.2185), day=2)],
    )
    plan = ItineraryPlan(itinerary_id="it-lintong", cities=["西安"], days=[d2, d4])
    assert _evict_wedge_strays(plan) == []


def test_wedge_never_evicts_tier1_ace():
    """王牌保护（兵马俑实录）：演出被甩去他日反成「多数伴日」——tier≤2
    名录王牌不剔（东方明珠四拍「不追改」同款锚档规则），楔的是被甩的
    演出，演出侧另有贴场馆换座收口。"""
    from app.services.agent.plan import _evict_wedge_strays
    from app.services.itinerary.models import ItineraryPlan

    bmy = GeoPoint(lon=109.2785, lat=34.3834)
    qyq = GeoPoint(lon=109.2790, lat=34.3830)
    hqg = GeoPoint(lon=109.2120, lat=34.3620)

    bmy_card = _visit("秦始皇帝陵博物院", 180, bmy, day=4)
    bmy_card.tier = 1
    d4 = DayPlan(
        day=4,
        base_city="西安",
        items=[
            bmy_card,
            _visit("华清宫", 120, hqg, day=4),
        ],
    )
    d1 = DayPlan(
        day=1,
        base_city="西安",
        items=[_visit("《秦俑情》", 90, qyq, day=1)],
    )
    plan = ItineraryPlan(itinerary_id="it-ace", cities=["西安"], days=[d1, d4])
    assert _evict_wedge_strays(plan) == []
    assert {i.name for i in d4.items if isinstance(i, VisitItem)} == {
        "秦始皇帝陵博物院",
        "华清宫",
    }
