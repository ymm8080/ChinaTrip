# -*- coding: utf-8 -*-
"""紧簇亲属归位终闸 _reunite_tight_kin（2026-11-08 西安钟鼓楼案）。

选层是容量优先——紧簇（≤2km，_TIGHT_CLUSTER_KM）亲属被逐动结构相位
拆到多天后，终装按不变量统一归位：并查集认簇（同 category 可数件、
同城、0<距离≤2km 连边），跨 ≥2 天的 ≥2 员簇选宿主日（可达成员数最
大、平票非边日优先、再低日号），可动件（边日/零亲属 + 非「tier≤2 钉
非边日」）挪宿主并清时刻、带「已归位」披露。判例护栏：到达日保 1 可
数件（返程日可清空）、宿主日可数 <4、tier≤2 不进边日宿主（东方明珠
四拍「不追改」同款锚档规则）、钉/软钉/必去永不动。

2026-11-08 晚修订（距离聚类优先拍板·组合排日）：锚 1/3 按终规格改写
——城心簇整簇归 D1（宿主按簇纯度，大雁塔 5.8km 异簇在 D2，D1 零异
簇）；东方明珠四拍「不追改」在终装层反转（王牌归簇通道，簇整归王
牌日），用户明示组合排日取代旧判例。
"""

from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    VisitItem,
)

# 西安实测锚点（活库坐标）：城心簇两两 ≤0.5km；雁塔簇 ≤0.75km；
# 大雁塔↔城心簇 ~5.8km 出紧簇圈；兵马俑远郊。
_ZL = GeoPoint(lon=108.9430, lat=34.2611)  # 西安钟楼
_GL = GeoPoint(lon=108.9435, lat=34.2602)  # 西安鼓楼
_CBL = GeoPoint(lon=108.9405, lat=34.2569)  # 城墙·碑林历史文化景区
_BLG = GeoPoint(lon=108.9402, lat=34.2544)  # 西安碑林博物馆（城心簇）
_DC = GeoPoint(lon=108.9430, lat=34.2595)  # 都城隍庙（城心簇第五点）
_DYT = GeoPoint(lon=108.9743, lat=34.2127)  # 大雁塔大唐芙蓉园景区
_SSE = GeoPoint(lon=108.9660, lat=34.2120)  # 长安十二时辰主题街区（↔大雁塔 ~0.77km）
_BMY = GeoPoint(lon=109.2785, lat=34.3834)  # 兵马俑（远郊）
# 上海锚（东方明珠四拍判例坐标）
_MZ = GeoPoint(lon=121.4998, lat=31.2397)  # 东方明珠
_HY = GeoPoint(lon=121.5020, lat=31.2380)  # 海洋馆
_BJ = GeoPoint(lon=121.5060, lat=31.2385)  # 滨江大道


def _visit(
    name: str,
    dur: int,
    loc: GeoPoint | None,
    day: int = 1,
    city: str = "西安",
    category: str | None = None,
    tier: int | None = None,
    pinned: bool = False,
) -> VisitItem:
    return VisitItem(
        item_id=f"v-{name}",
        name=name,
        city=city,
        day=day,
        duration_minutes=dur,
        location=loc,
        category=category,
        tier=tier,
        pinned=pinned,
    )


def test_drum_tower_reunites_to_wall_day():
    """钟鼓楼案主锚（终规格 2026-11-08 距离聚类优先）：城心簇
    钟楼(D1)/城墙·碑林(D2)/鼓楼(D4) 拆三天——宿主按簇纯度选 D1（大雁
    塔 5.8km 异簇件在 D2，D1 零异簇），城墙·碑林+鼓楼归 D1 与钟楼成整
    簇；大雁塔独占 D2（异簇不混日），兵马俑独点不受牵连。"""
    from app.services.agent.plan import _reunite_tight_kin

    zl = _visit("西安钟楼", 40, _ZL, day=1)
    dyt = _visit("大雁塔大唐芙蓉园景区", 180, _DYT, day=2)
    cbl = _visit("城墙·碑林历史文化景区", 90, _CBL, day=2)
    bmy = _visit("秦始皇帝陵博物院", 180, _BMY, day=3)
    gl = _visit("西安鼓楼", 40, _GL, day=4)
    plan = ItineraryPlan(
        itinerary_id="it-xian-kin",
        cities=["西安"],
        days=[
            DayPlan(day=1, base_city="西安", items=[zl]),
            DayPlan(day=2, base_city="西安", items=[dyt, cbl]),
            DayPlan(day=3, base_city="西安", items=[bmy]),
            DayPlan(day=4, base_city="西安", items=[gl]),
        ],
    )
    _reunite_tight_kin(plan)
    assert gl.day == cbl.day == zl.day == 1  # 城心簇整簇归 D1
    d1_names = [i.name for i in plan.days[0].items if isinstance(i, VisitItem)]
    assert {"西安钟楼", "西安鼓楼", "城墙·碑林历史文化景区"} <= set(d1_names)
    assert dyt.day == 2  # 大雁塔独占 D2，纯雁塔日
    assert bmy.day == 3  # 独点（无簇）不受牵连
    assert any("已归位" in a for a in plan.assumptions)


def test_citywalk_rejoins_venue_cluster():
    """雁塔簇主锚：十二时辰街区（citywalk）被甩返程日 D3——边日可动，
    归位到非边宿主 D2 与大雁塔同日（平票非边日优先）。"""
    from app.services.agent.plan import _reunite_tight_kin  # 并行实现中（TDD 红基线）

    zl = _visit("西安钟楼", 40, _ZL, day=1)
    dyt = _visit("大雁塔大唐芙蓉园景区", 180, _DYT, day=2)
    sse = _visit("长安十二时辰主题街区", 120, _SSE, day=3, category="citywalk")
    plan = ItineraryPlan(
        itinerary_id="it-sse-kin",
        cities=["西安"],
        days=[
            DayPlan(day=1, base_city="西安", items=[zl]),
            DayPlan(day=2, base_city="西安", items=[dyt]),
            DayPlan(day=3, base_city="西安", items=[sse]),
        ],
    )
    _reunite_tight_kin(plan)
    assert sse.day == 2
    d2_names = [i.name for i in plan.days[1].items if isinstance(i, VisitItem)]
    assert {"大雁塔大唐芙蓉园景区", "长安十二时辰主题街区"} <= set(d2_names)
    assert zl.day == 1  # 孤点（无簇）不动


def test_tier1_ace_cluster_reunifies():
    """东方明珠四拍终装层反转锚（2026-11-08 距离聚类优先拍板·组合排
    日，用户明示取代「不追改」）：明珠/海洋馆/滨江 ≤0.7km 同簇拆两天
    ——tier1 王牌孤悬 D1（本日零同簇伴）走王牌归簇通道可动，D2 返程
    边日可清空，整簇原子归 D1 王牌日。大块头 180min 不上边日宿主的锚
    档规则仍在（见 test_tier2_not_pushed_to_edge_host）。"""
    from app.services.agent.plan import _reunite_tight_kin

    mz = _visit("东方明珠", 180, _MZ, day=1, city="上海", tier=1)
    hy = _visit("海洋馆", 90, _HY, day=2, city="上海")
    bj = _visit("滨江大道", 90, _BJ, day=2, city="上海")
    plan = ItineraryPlan(
        itinerary_id="it-mz-kin",
        cities=["上海"],
        days=[
            DayPlan(day=1, base_city="上海", items=[mz]),
            DayPlan(day=2, base_city="上海", items=[hy, bj]),
        ],
    )
    _reunite_tight_kin(plan)
    assert mz.day == 1
    assert {i.name for i in plan.days[0].items if isinstance(i, VisitItem)} == {
        "东方明珠",
        "海洋馆",
        "滨江大道",
    }


def test_pinned_never_moves():
    """铁律 19 护栏：用户钉住的件（pinned）即便孤悬返程日也不归位。"""
    from app.services.agent.plan import _reunite_tight_kin  # 并行实现中（TDD 红基线）

    zl = _visit("西安钟楼", 40, _ZL, day=1)
    dyt = _visit("大雁塔大唐芙蓉园景区", 180, _DYT, day=2)
    sse = _visit(
        "长安十二时辰主题街区", 120, _SSE, day=3, category="citywalk", pinned=True
    )
    plan = ItineraryPlan(
        itinerary_id="it-pin-kin",
        cities=["西安"],
        days=[
            DayPlan(day=1, base_city="西安", items=[zl]),
            DayPlan(day=2, base_city="西安", items=[dyt]),
            DayPlan(day=3, base_city="西安", items=[sse]),
        ],
    )
    _reunite_tight_kin(plan)
    assert sse.day == 3
    assert sse in plan.days[2].items


def test_full_host_receives_no_one():
    """容量护栏：宿主日可数件已达 4 帽（4/日帽）——第五员留在本日，
    不为归位硬塞满员日。"""
    from app.services.agent.plan import _reunite_tight_kin  # 并行实现中（TDD 红基线）

    bmy = _visit("秦始皇帝陵博物院", 180, _BMY, day=1)
    a = _visit("西安钟楼", 40, _ZL, day=2)
    b = _visit("西安鼓楼", 40, _GL, day=2)
    c = _visit("城墙·碑林历史文化景区", 180, _CBL, day=2)
    d = _visit("西安碑林博物馆", 90, _BLG, day=2)
    e = _visit("都城隍庙", 40, _DC, day=3)
    plan = ItineraryPlan(
        itinerary_id="it-cap-kin",
        cities=["西安"],
        days=[
            DayPlan(day=1, base_city="西安", items=[bmy]),
            DayPlan(day=2, base_city="西安", items=[a, b, c, d]),
            DayPlan(day=3, base_city="西安", items=[e]),
        ],
    )
    _reunite_tight_kin(plan)
    assert e.day == 3  # D2 已满 4，第五员不进
    assert len(
        [i for i in plan.days[1].items if isinstance(i, VisitItem)]
    ) == 4


def test_tier2_not_pushed_to_edge_host():
    """锚档护栏：tier2 件孤悬非边日 D2——tier≤2 不上边日宿主（D3 返程
    日），不得被推去返程日凑簇。"""
    from app.services.agent.plan import _reunite_tight_kin  # 并行实现中（TDD 红基线）

    x = _visit("西安钟楼", 40, _ZL, day=1)
    w = _visit("西安鼓楼", 40, _GL, day=2, tier=2)
    y = _visit("城墙·碑林历史文化景区", 180, _CBL, day=3)
    z = _visit("西安碑林博物馆", 90, _BLG, day=3)
    plan = ItineraryPlan(
        itinerary_id="it-tier-kin",
        cities=["西安"],
        days=[
            DayPlan(day=1, base_city="西安", items=[x]),
            DayPlan(day=2, base_city="西安", items=[w]),
            DayPlan(day=3, base_city="西安", items=[y, z]),
        ],
    )
    _reunite_tight_kin(plan)
    assert w.day == 2
    assert w not in plan.days[2].items  # 未被推进返程日 D3


def test_nonedge_zero_kin_member_can_move():
    """正向通道：中档件（tier4）孤悬非边日 D3（零同簇亲属）——归位到
    亲属多数的非边宿主 D2（D4 返程日存在，D2/D3 均非边日）。"""
    from app.services.agent.plan import _reunite_tight_kin  # 并行实现中（TDD 红基线）

    bmy = _visit("秦始皇帝陵博物院", 180, _BMY, day=1)
    a = _visit("西安钟楼", 40, _ZL, day=2)
    b = _visit("西安鼓楼", 40, _GL, day=2)
    m = _visit("城墙·碑林历史文化景区", 180, _CBL, day=3, tier=4)
    plan = ItineraryPlan(
        itinerary_id="it-move-kin",
        cities=["西安"],
        days=[
            DayPlan(day=1, base_city="西安", items=[bmy]),
            DayPlan(day=2, base_city="西安", items=[a, b]),
            DayPlan(day=3, base_city="西安", items=[m]),
            DayPlan(day=4, base_city="西安", items=[]),
        ],
    )
    _reunite_tight_kin(plan)
    assert m.day == 2
    d2_names = [i.name for i in plan.days[1].items if isinstance(i, VisitItem)]
    assert "城墙·碑林历史文化景区" in d2_names
    assert any("已归位" in a_ for a_ in plan.assumptions)
