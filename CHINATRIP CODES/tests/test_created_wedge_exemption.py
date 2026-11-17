# -*- coding: utf-8 -*-
"""手建卡（CREATED lane）楔子清障豁免（2026-11-08 拍板乙·三级梯
心愿>CREATED>TAG）。

用户案：手建「长安十二时辰主题街区」（citywalk）被 _evict_wedge_strays
整删——CREATED 标记死在选层候选（_created_lane），活不过装配。三锚：
① VisitItem.created 落字段（默认 False，装配期透传）；
② 楔入态手建卡永不下杀手：kin 多数日满员 → 踢最弱 TAG 强制归位
   （_stack_uncashable 真裁决过才动真盘，被踢者重排/移除留痕）；
③ 踢不动/审不过 → 原地保留带披露（宁乱排勿删手建卡）。
非手建卡楔子语义原样（回归锚）。
"""

from app.services.agent.plan import _evict_wedge_strays
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    VisitItem,
)

# 钟楼簇（手建卡 + 近邻）：互相 ≤2km
_V = GeoPoint(lon=108.9430, lat=34.2611)  # 长安十二时辰主题街区
_GL = GeoPoint(lon=108.9432, lat=34.2608)  # 鼓楼 ~40m
_BLG = GeoPoint(lon=108.9402, lat=34.2544)  # 碑林馆 ~0.9km
_CQ = GeoPoint(lon=108.9410, lat=34.2560)  # 城墙 ~0.6km
_VIC = GeoPoint(lon=108.9425, lat=34.2600)  # 让位牺牲品（簇内）
_DYT = GeoPoint(lon=108.9644, lat=34.2185)  # 大雁塔 ~5km 远核心


def _visit(
    name: str,
    dur: int,
    loc: GeoPoint | None,
    day: int = 1,
    *,
    category: str = "sight",
    tier: int | None = None,
    pinned: bool = False,
    created: bool = False,
) -> VisitItem:
    return VisitItem(
        item_id=f"v-{name}",
        name=name,
        city="西安",
        day=day,
        duration_minutes=dur,
        location=loc,
        category=category,
        tier=tier,
        pinned=pinned,
        created=created,
    )


def _plan(d2: DayPlan, d3: DayPlan) -> ItineraryPlan:
    return ItineraryPlan(
        itinerary_id="it-created-wedge", cities=["西安"], days=[d2, d3]
    )


def _kin_day(day: int = 3, *, v_dur: int | None = None, v: VisitItem | None = None):
    """D3 kin 多数日：3 近邻 + tier5 短牺牲品 = 4 可数（满员）。"""
    created = v or (
        _visit(
            "长安十二时辰主题街区",
            v_dur if v_dur is not None else 90,
            _V,
            day=day,
            category="citywalk",
            created=True,
        )
    )
    return DayPlan(
        day=day,
        base_city="西安",
        items=[
            _visit("西安鼓楼", 40, _GL, day=day, tier=3),
            _visit("西安碑林博物馆", 90, _BLG, day=day, tier=4),
            _visit("西安城墙", 60, _CQ, day=day, tier=3),
            _visit("网红打卡墙", 60, _VIC, day=day, tier=5),
        ],
    ), created


def test_created_wedged_full_kin_day_force_reunites():
    """kin 多数日满员：踢最弱 TAG（tier5 短件）把手建卡归位——手建卡
    永不进 dropped，牺牲品无位重排按 TAG 口径移除留痕。"""
    d3, v = _kin_day()
    # D2 本日远核心（大雁塔 720min 吃满窗 → 牺牲品重排也进不来）
    d2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            _visit("大雁塔", 720, _DYT, day=2, tier=3),
            v,
        ],
    )
    # v 落 D2（楔入态：本日零 kin + 远核心在册）
    v.day = 2
    plan = _plan(d2, d3)
    dropped = _evict_wedge_strays(plan)
    assert v.name not in dropped
    assert v.day == 3
    assert any(i is v for i in d3.items)
    assert not any(i is v for i in d2.items)
    assert dropped == ["网红打卡墙"]  # 牺牲品重排不进（720min 吃满）→ 移除留痕
    assert not any(i.name == "网红打卡墙" for i in d3.items)
    assert any("已归位第3天" in a for a in plan.assumptions)
    assert any("让位" in a for a in plan.assumptions)
    assert any("网红打卡墙" in a and "未排入" in a for a in plan.assumptions)


def test_created_wedged_oracle_fail_stays():
    """兑现审不过（600min 塞不进满员 kin 日）：牺牲品原位归还，手建卡
    原地保留带披露——不删除。"""
    d3, v = _kin_day(v_dur=600)
    d2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            _visit("大雁塔", 120, _DYT, day=2, tier=3),
            v,
        ],
    )
    v.day = 2
    vic = next(i for i in d3.items if i.name == "网红打卡墙")
    vic_idx = d3.items.index(vic)
    plan = _plan(d2, d3)
    dropped = _evict_wedge_strays(plan)
    assert dropped == []
    assert v.day == 2
    assert any(i is v for i in d2.items)
    assert d3.items.index(vic) == vic_idx  # 牺牲品原位归还
    assert {i.name for i in d3.items} == {
        "西安鼓楼",
        "西安碑林博物馆",
        "西安城墙",
        "网红打卡墙",
    }
    assert any("不删除" in a and "手动添加" in a for a in plan.assumptions)


def test_tag_wedged_still_dropped():
    """非手建卡楔子语义原样（回归锚）：经典楔入照删。"""
    zl = _visit("西安钟楼", 40, _V, day=2)  # 非手建
    d2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            _visit("大雁塔", 180, _DYT, day=2),
            zl,
        ],
    )
    d3 = DayPlan(
        day=3,
        base_city="西安",
        items=[
            _visit("西安鼓楼", 40, _GL, day=3),
            _visit("西安碑林博物馆", 90, _BLG, day=3),
        ],
    )
    plan = _plan(d2, d3)
    dropped = _evict_wedge_strays(plan)
    assert dropped == ["西安钟楼"]
    assert [i.name for i in d2.items if isinstance(i, VisitItem)] == ["大雁塔"]
    assert any("近邻多在第3天" in a for a in plan.assumptions)


def test_created_flag_and_no_victim_exemption_path():
    """created 字段单元锚 + 手建卡楔入但 kin 日无可踢（近邻全钉）→
    豁免通道原地保留，永不进 dropped。"""
    plain = _visit("普通件", 60, _V, day=2)
    assert plain.created is False
    card = _visit(
        "长安十二时辰主题街区", 90, _V, day=2, category="citywalk", created=True
    )
    assert card.created is True

    v = _visit("长安十二时辰主题街区", 90, _V, day=2, category="citywalk", created=True)
    d2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            _visit("大雁塔", 120, _DYT, day=2),
            v,
        ],
    )
    d3 = DayPlan(
        day=3,
        base_city="西安",
        items=[
            _visit("西安鼓楼", 40, _GL, day=3, tier=3, pinned=True),
            _visit("西安碑林博物馆", 90, _BLG, day=3, tier=3, pinned=True),
        ],
    )
    plan = _plan(d2, d3)
    dropped = _evict_wedge_strays(plan)
    assert dropped == []
    assert v.day == 2
    assert any("手动添加" in a for a in plan.assumptions)
