# -*- coding: utf-8 -*-
"""CURATED 保护 + 簇日纯度闸（2026-11-08 拍板）。

拍板①「异簇不混日」：成族之日（同簇可数件 ≥2 在册）不得插排其它
非同族景点——_purify_cluster_days 把距全簇 >15km（_DISTRICT_DAY_KM
同片区圈外，2026-11-08 dde6cce 临潼案口径；此前 >5km）的异簇件挪走
不删（无日可收才删+披露，宁缺勿混）；近距离餐厅可以插排（food 永
不动），pinned/soft_pin/must 永不动。
拍板②「我说的是 CURATED，不是 CREATED flag」：长安十二时辰主题街区
是 curated（精选库）卡——curated 卡永不进删除闸；判据：≤120min
citywalk 在 16:30 前一定排得进，被级联甩出家门后删除闸必须救回。
宴类=簇跟随者规则（多宴只挪有簇伴日否则取消+披露）已定稿，不受
curated 豁免影响。
"""

from datetime import time
from types import SimpleNamespace

from app.services.agent.plan import (
    _cand_is_curated,
    _day_purity_sweep,
    _drop_untimed_visits,
    _enforce_show_per_day,
    _evict_wedge_strays,
    _purify_cluster_days,
    _reconcile_transfer_days,
    _transfer_day_sweep,
    drop_dangling_visits,
)
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    TransferItem,
    VisitItem,
)
from app.services.poi_details import _candidate_from_row

# 钟楼簇（curated 卡 + 近邻）：互相 ≤2km
_V = GeoPoint(lon=108.9430, lat=34.2611)  # 长安十二时辰主题街区
_GL = GeoPoint(lon=108.9432, lat=34.2608)  # 鼓楼 ~40m
_BLG = GeoPoint(lon=108.9402, lat=34.2544)  # 碑林馆 ~0.9km
_CQ = GeoPoint(lon=108.9410, lat=34.2560)  # 城墙 ~0.6km
_VIC = GeoPoint(lon=108.9425, lat=34.2600)  # 让位牺牲品（簇内）
# 大雁塔簇（第二簇）：与本簇拉开 >5km
_DYT = GeoPoint(lon=108.9660, lat=34.2170)  # 大雁塔 ~5.4km
_DTB = GeoPoint(lon=108.9660, lat=34.2120)  # 大唐不夜城 ~5.9km
# 临潼片区三角（实测坐标）：兵马俑↔华清宫 6.9km、华清宫↔骊山 1.6km，
# 距城心 ~30km——片区伴锚用（2026-11-08 临潼案拍板「按距离是一个组合
# 放同一天」）
_HQG = GeoPoint(lon=109.2151, lat=34.3589)  # 华清宫
_LISHAN = GeoPoint(lon=109.2130, lat=34.3729)  # 临潼骊山
_BMY = GeoPoint(lon=109.2820, lat=34.3862)  # 秦始皇帝陵博物院
# 远簇（purity 三测专用，2026-11-08 dde6cce 临潼案口径：异簇判定放宽到
# _DISTRICT_DAY_KM=15km 同片区伴不逐——原 5.4km 布点落进豁免带，簇须
# 布到 >15km 圈外才算异簇）
_DYT_FAR = GeoPoint(lon=109.1900, lat=34.2100)  # 远簇锚 ~23km
_DTB_FAR = GeoPoint(lon=109.1900, lat=34.2050)  # 远簇伴 ~23km


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
    curated: bool = False,
    start: time | None = None,
    city: str = "西安",
) -> VisitItem:
    return VisitItem(
        item_id=f"v-{name}-{day}",
        name=name,
        city=city,
        day=day,
        duration_minutes=dur,
        location=loc,
        category=category,
        tier=tier,
        pinned=pinned,
        created=created,
        curated=curated,
        start_time=start,
        end_time=None,
    )


def _plan(*days: DayPlan) -> ItineraryPlan:
    return ItineraryPlan(
        itinerary_id="it-curated-purity", cities=["西安"], days=list(days)
    )


# ---------------------------------------------------------------- 拍板② CURATED


def test_curated_marker_archeology():
    """池侧 curated 判据（_cand_is_curated）：source / tags / poi_id 前缀
    三路；ta/lp/viator 同档不算精选库。"""
    assert _cand_is_curated({"source": "curated"}) is True
    assert _cand_is_curated({"tags": ["intl", "curated"]}) is True
    assert (
        _cand_is_curated(
            {"source_poi_id": "curated:西安:长安十二时辰·唐宴", "category": "food"}
        )
        is True
    )
    assert _cand_is_curated({"source": "amap", "tags": []}) is False
    assert _cand_is_curated({"source": "tripadvisor"}) is False
    assert _cand_is_curated({"source": "show", "tags": []}) is False
    assert _cand_is_curated({}) is False


def test_curated_flag_defaults_false_and_field_exists():
    plain = _visit("普通件", 60, _V, day=2)
    assert plain.curated is False
    card = _visit(
        "长安十二时辰主题街区", 120, _V, day=2, category="citywalk", curated=True
    )
    assert card.curated is True


def _kin_day(day: int = 3, *, v: VisitItem) -> DayPlan:
    """D3 kin 多数日：3 近邻 + tier5 短牺牲品 = 4 可数（满员）。"""
    return DayPlan(
        day=day,
        base_city="西安",
        items=[
            _visit("西安鼓楼", 40, _GL, day=day, tier=3),
            _visit("西安碑林博物馆", 90, _BLG, day=day, tier=4),
            _visit("西安城墙", 60, _CQ, day=day, tier=3),
            _visit("网红打卡墙", 60, _VIC, day=day, tier=5),
        ],
    )


def test_curated_wedged_full_kin_day_force_reunites():
    """十二时辰形态（拍板②判据）：curated citywalk 120min、簇伴多数在
    别日、本日远核心——楔子闸不删，踢最弱 TAG 强制归位。"""
    v = _visit(
        "长安十二时辰主题街区", 120, _V, day=2, category="citywalk", curated=True
    )
    d3 = _kin_day(3, v=v)
    d2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            _visit("大雁塔", 720, _DYT, day=2, tier=3),
            v,
        ],
    )
    plan = _plan(d2, d3)
    dropped = _evict_wedge_strays(plan)
    assert v.name not in dropped
    assert v.day == 3
    assert any(i is v for i in d3.items)
    assert not any(i is v for i in d2.items)
    assert dropped == ["网红打卡墙"]  # 牺牲品重排不进（720min 吃满）→ 移除留痕
    assert any("已归位第3天" in a for a in plan.assumptions)
    assert any("精选库" in a and "让位" in a for a in plan.assumptions)


def test_curated_wedged_oracle_fail_stays():
    """兑现审不过（600min 塞不进满员 kin 日）：牺牲品原位归还，curated
    卡原地保留带披露——不删除。"""
    v = _visit(
        "长安十二时辰主题街区", 600, _V, day=2, category="citywalk", curated=True
    )
    d3 = _kin_day(3, v=v)
    d2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            _visit("大雁塔", 120, _DYT, day=2, tier=3),
            v,
        ],
    )
    plan = _plan(d2, d3)
    dropped = _evict_wedge_strays(plan)
    assert dropped == []
    assert v.day == 2
    assert any(i is v for i in d2.items)
    assert any("精选库" in a and "不删除" in a for a in plan.assumptions)


def test_curated_never_kicked_as_wedge_victim():
    """kin 日满员且唯一可踢件是 curated 卡：不可踢——curated 豁免卡走
    原地保留（宁乱排勿删，两张精选卡都不丢）。"""
    v = _visit("长安十二时辰主题街区", 90, _V, day=2, category="citywalk", curated=True)
    other_curated = _visit(
        "长安十二时辰·唐宴街区", 60, _VIC, day=3, category="citywalk", curated=True
    )
    d3 = DayPlan(
        day=3,
        base_city="西安",
        items=[
            _visit("西安鼓楼", 40, _GL, day=3, tier=3, pinned=True),
            _visit("西安碑林博物馆", 90, _BLG, day=3, tier=3, pinned=True),
            other_curated,
        ],
    )
    d2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            _visit("大雁塔", 120, _DYT, day=2),
            v,
        ],
    )
    plan = _plan(d2, d3)
    dropped = _evict_wedge_strays(plan)
    assert dropped == []
    assert v.day == 2  # 无可踢牺牲品 → 原地保留
    assert any(i is other_curated for i in d3.items)  # curated 牺牲品豁免
    assert any("精选库" in a and "不删除" in a for a in plan.assumptions)


# ---------------------------------------------------------------- 拍板① 簇日纯度


def test_purity_moves_stray_out_of_cluster_day():
    """异簇景点被纯度闸挪出簇日：D2 被远簇主导，钟楼距全簇 >15km
    （_DISTRICT_DAY_KM 同片区圈外，2026-11-08 口径）=异簇插排——挪去
    有它自己簇伴的 D3（清时刻+双语披露），不删。"""
    zl = _visit("西安钟楼", 40, _V, day=2)
    d2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            _visit("大雁塔", 120, _DYT_FAR, day=2, tier=3),
            _visit("大唐不夜城", 90, _DTB_FAR, day=2, tier=3),
            zl,
        ],
    )
    d3 = DayPlan(
        day=3,
        base_city="西安",
        items=[
            _visit("西安鼓楼", 40, _GL, day=3, tier=3),
            _visit("西安碑林博物馆", 90, _BLG, day=3, tier=4),
        ],
    )
    plan = _plan(d2, d3)
    dropped = _purify_cluster_days(plan)
    assert dropped == []
    assert zl.day == 3
    assert any(i is zl for i in d3.items)
    assert not any(i is zl for i in d2.items)
    assert zl.start_time is None and zl.end_time is None
    assert any("已移出第2天" in a and "片区连贯" in a for a in plan.assumptions)


def test_purity_food_and_entertainment_never_moved():
    """近距离餐厅可以插排：簇日上的 food/hotel/entertainment 永不动。"""
    far_food = _visit("回民街老米家泡馍", 60, _V, day=2, category="food")
    far_show = _visit("长安十二时辰夜秀", 90, _V, day=2, category="entertainment")
    d2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            _visit("大雁塔", 120, _DYT, day=2, tier=3),
            _visit("大唐不夜城", 90, _DTB, day=2, tier=3),
            far_food,
            far_show,
        ],
    )
    d3 = DayPlan(
        day=3,
        base_city="西安",
        items=[_visit("西安鼓楼", 40, _GL, day=3, tier=3)],
    )
    plan = _plan(d2, d3)
    dropped = _purify_cluster_days(plan)
    assert dropped == []
    assert any(i is far_food for i in d2.items)
    assert any(i is far_show for i in d2.items)
    assert not any("移出" in a for a in plan.assumptions)


def test_purity_pinned_never_moved():
    """pinned/soft_pin/must 永不动：钉住的异簇件留在簇日。"""
    zl = _visit("西安钟楼", 40, _V, day=2, pinned=True)
    d2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            _visit("大雁塔", 120, _DYT, day=2, tier=3),
            _visit("大唐不夜城", 90, _DTB, day=2, tier=3),
            zl,
        ],
    )
    d3 = DayPlan(day=3, base_city="西安", items=[])
    plan = _plan(d2, d3)
    dropped = _purify_cluster_days(plan)
    assert dropped == []
    assert any(i is zl for i in d2.items)
    assert zl.day == 2


def test_purity_drops_when_no_room():
    """宁缺勿混：同城他日全满（4/日帽）→ 异簇件删除+披露。"""
    zl = _visit("西安钟楼", 40, _V, day=2)
    d2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            _visit("大雁塔", 120, _DYT_FAR, day=2, tier=3),
            _visit("大唐不夜城", 90, _DTB_FAR, day=2, tier=3),
            zl,
        ],
    )
    d3 = DayPlan(
        day=3,
        base_city="西安",
        items=[
            _visit("西安鼓楼", 40, _GL, day=3, tier=3),
            _visit("西安碑林博物馆", 90, _BLG, day=3, tier=4),
            _visit("西安城墙", 60, _CQ, day=3, tier=3),
            _visit("网红打卡墙", 60, _VIC, day=3, tier=5),
        ],
    )
    plan = _plan(d2, d3)
    dropped = _purify_cluster_days(plan)
    assert dropped == ["西安钟楼"]
    assert not any(i is zl for i in d2.items)
    assert any("片区连贯未排入" in a for a in plan.assumptions)


def test_purity_keeps_curated_when_no_room():
    """curated 卡无日可收也永不删：原地保留带披露。"""
    v = _visit(
        "长安十二时辰主题街区", 120, _V, day=2, category="citywalk", curated=True
    )
    d2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            _visit("大雁塔", 120, _DYT_FAR, day=2, tier=3),
            _visit("大唐不夜城", 90, _DTB_FAR, day=2, tier=3),
            v,
        ],
    )
    d3 = DayPlan(
        day=3,
        base_city="西安",
        items=[
            _visit("西安鼓楼", 40, _GL, day=3, tier=3),
            _visit("西安碑林博物馆", 90, _BLG, day=3, tier=4),
            _visit("西安城墙", 60, _CQ, day=3, tier=3),
            _visit("网红打卡墙", 60, _VIC, day=3, tier=5),
        ],
    )
    plan = _plan(d2, d3)
    dropped = _purify_cluster_days(plan)
    assert dropped == []
    assert any(i is v for i in d2.items)
    assert v.day == 2
    assert any("不删除" in a and "暂留" in a for a in plan.assumptions)


def test_purity_stray_allowed_within_5km_of_cluster():
    """距簇 ≤5km 的近伴不算异簇（_NEAR_SAMEDAY_KM 口径）——留在簇日。"""
    near = _visit("陕西历史博物馆", 90, GeoPoint(lon=108.9500, lat=34.2400), day=2)
    d2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            _visit("大雁塔", 120, _DYT, day=2, tier=3),
            _visit("大唐不夜城", 90, _DTB, day=2, tier=3),
            near,
        ],
    )
    plan = _plan(d2)
    dropped = _purify_cluster_days(plan)
    assert dropped == []
    assert any(i is near for i in d2.items)
    assert near.day == 2


def test_purity_district_mate_within_15km_stays():
    """临潼案锚（2026-11-08 拍板「兵马俑/华清宫按距离是一个组合放同一
    天」）：兵马俑距华清宫+骊山簇 6.9km——5km 同日圈外但 15km 片区圈内
    =同片区伴，不逐（旧 >5km 口径会把临潼组合拆两天，兵马俑被逐去
    到达日实录）。"""
    bmy = _visit("秦始皇帝陵博物院", 90, _BMY, day=2, tier=1)
    d2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            _visit("华清宫", 90, _HQG, day=2, tier=2),
            _visit("临潼骊山风景名胜区", 180, _LISHAN, day=2, tier=9),
            bmy,
        ],
    )
    d3 = DayPlan(
        day=3, base_city="西安", items=[_visit("西安鼓楼", 40, _GL, day=3, tier=3)]
    )
    plan = _plan(d2, d3)
    dropped = _purify_cluster_days(plan)
    assert dropped == []
    assert bmy.day == 2
    assert any(i is bmy for i in d2.items)
    assert not any("移出" in a for a in plan.assumptions)


def test_purity_heavy_stray_avoids_arrival_day():
    """到达日让位锚（2026-11-08 拍板「到达日只适合简单的 CITYWALK 或
    SHOW」）：tier≤2 王牌被纯度闸逐出时，空到达日 D1 与空 D3 同为候选
    ——day_index 原会首选 D1；重物让位后改落 D3。孤窗（无他日）不受
    影响（软让不硬拦）。"""
    zl = _visit("西安钟楼", 40, _V, day=2, tier=1)
    d1 = DayPlan(day=1, base_city="西安", items=[])
    d2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            _visit("远簇锚", 120, _DYT_FAR, day=2, tier=3),
            _visit("远簇伴", 90, _DTB_FAR, day=2, tier=3),
            zl,
        ],
    )
    d3 = DayPlan(
        day=3,
        base_city="西安",
        items=[
            _visit("大雁塔", 120, _DYT, day=3, tier=3),
            _visit("大唐不夜城", 90, _DTB, day=3, tier=3),
        ],
    )
    plan = _plan(d1, d2, d3)
    dropped = _purify_cluster_days(plan)
    assert dropped == []
    assert zl.day == 3
    assert any(i is zl for i in d3.items)
    assert not any(i is zl for i in d1.items)


# ------------------------------------------- 每场闸删除路径的 curated 豁免


def _show(name: str, lon: float, lat: float, day: int, *, curated: bool = False):
    return _visit(
        name,
        80,
        GeoPoint(lon=lon, lat=lat),
        day,
        category="entertainment",
        curated=curated,
        start=time(19, 30),
    )


def test_show_gate_keeps_curated_when_no_free_day():
    """全城无空演出日：curated 演出卡不点名删除——原地保留带披露。"""
    s1 = _visit("市区景点", 120, GeoPoint(lon=108.95, lat=34.27), day=1)
    a = _show("贴场演出A", 108.95, 34.27, 1)
    b = _show("精选演出B", 108.9660, 34.2170, 1, curated=True)
    b.start_time = time(20, 0)
    d1 = DayPlan(day=1, base_city="西安", items=[s1, a, b])
    s2 = _visit("西郊景点", 120, GeoPoint(lon=108.90, lat=34.26), day=2)
    c = _show("占席演出C", 108.90, 34.26, 2)
    d2 = DayPlan(day=2, base_city="西安", items=[s2, c])
    plan = _plan(d1, d2)
    _enforce_show_per_day(plan)
    assert any(i is b for i in d1.items)  # curated 不删
    assert b.start_time == time(20, 0)
    assert not any(b.name in a_ and "未排" in a_ for a_ in plan.assumptions)
    assert any("精选库" in a_ and "不删除" in a_ for a_ in plan.assumptions)


def test_show_gate_never_sacrifices_curated_victim():
    """最弱场馆锚牺牲品扫描跳过 curated 卡：弱锚精选卡不被删腾位，
    改由本卡自己走点名移除口径（TAG 梯）。"""
    s1 = _visit("市区景点", 120, GeoPoint(lon=108.95, lat=34.27), day=1)
    a = _show("贴场演出A", 108.95, 34.27, 1)
    b = _show("远场演出B", 108.9660, 34.2170, 1)  # 弱锚 extra（非 curated）
    d1 = DayPlan(day=1, base_city="西安", items=[s1, a, b])
    s2 = _visit("西郊景点", 120, GeoPoint(lon=108.90, lat=34.26), day=2)
    c = _show("精选演出C", 108.9660, 34.2170, 2, curated=True)  # 全城最弱锚
    d2 = DayPlan(day=2, base_city="西安", items=[s2, c])
    plan = _plan(d1, d2)
    _enforce_show_per_day(plan)
    assert any(i is c for i in d2.items)  # curated 牺牲品豁免
    assert c.start_time == time(19, 30)
    assert not any(i is b for i in d1.items)  # B 自己让位（原口径）
    assert any(b.name in a_ and "未排" in a_ for a_ in plan.assumptions)


def test_show_gate_untimed_curated_kept():
    """闸后清扫段（全天排不上时刻的演出点名移除）对 curated 卡不删：
    留待终闸清算再给一次落时刻机会，带披露。moved 由宴位取消路径触发
    （簇跟随者规则原样，不受 curated 豁免影响）。"""
    s1 = _visit("市区景点", 120, GeoPoint(lon=108.95, lat=34.27), 1, start=time(9, 0))
    a = _show("贴场演出A", 108.95, 34.27, 1)
    bx = _visit(
        "长安十二时辰·唐宴",
        90,
        GeoPoint(lon=108.9660, lat=34.2170),
        1,
        category="food",
        curated=True,
    )
    bx.poi_id = "curated:西安:长安十二时辰·唐宴"
    d1 = DayPlan(day=1, base_city="西安", items=[s1, a, bx])
    s2 = _visit("西郊景点", 120, GeoPoint(lon=108.90, lat=34.26), 2, start=time(9, 0))
    c = _show("占席演出C", 108.90, 34.26, 2)
    d2 = DayPlan(day=2, base_city="西安", items=[s2, c])
    big = _visit("大块头景点", 720, GeoPoint(lon=108.9430, lat=34.2960), 3)
    e = _show("精选演出E", 108.90, 34.26, 3, curated=True)
    e.start_time = None  # 无时刻：D3 被 720min 大块头吃满
    d3 = DayPlan(day=3, base_city="西安", items=[big, e])
    plan = _plan(d1, d2, d3)
    _enforce_show_per_day(plan)
    assert any(i is e for i in d3.items)  # curated 无时刻也不删
    assert any("精选库" in a_ and "不删除" in a_ for a_ in plan.assumptions)


# ------------------------------------------- 二拍补刀（2026-11-08 二轮）：
# 探针实录（ops/_tmp_cluster_split_probe_after.txt）：十二时辰经
# fallback sequencing 排不下时刻后被「始终排不下时刻，已从行程移除」
# 整卡删除——发射点 _drop_untimed_from_day。二拍：curated/created/
# tier≤2 王牌在无时刻清扫链永不删（原地保留+披露）；让位弹座池同
# 豁免（弹出的牺牲品无宿主天即蒸发=变相删除）。----


def _row(**over):
    """活库形状的 POI 行（poi_details._candidate_from_row 属性面）。"""
    base = dict(
        source_poi_id="sygic:西安:长安十二时辰主题街区",
        name_zh="长安十二时辰主题街区",
        name_en="Chang'an Twelve Hours Theme Block",
        address_en=None,
        intro_en=None,
        opening_hours_en=None,
        review_tags_en=[],
        city="西安",
        category="citywalk",
        address="西安市雁塔区",
        opening_hours="10:00-22:00",
        source="show",
        rating=4.6,
        rating_count=1000,
        rating_source=None,
        tags=["intl", "sygic", "show", "curated"],
        best_visit_time="any",
        suggested_duration_min=240,
        indoor=False,
        rain_ok=True,
        review_tags=[],
        intro="唐风沉浸式主题街区",
        reservation_required=False,
        reservation_advance_days=None,
        booking_url=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_curated_tags_path_end_to_end_from_row():
    """端到端锚（库行 tags=["intl","sygic","show","curated"]，快照
    pois_curated_tag_bak_20261108）：ORM 行 → _candidate_from_row（tags
    透传）→ _cand_is_curated tags 路命中（source=show 非精选源）→
    _assemble_plan 同式装配 VisitItem.curated=True。"""
    cand = _candidate_from_row(_row(), "POINT(108.9430 34.2611)")
    assert cand["tags"] == ["intl", "sygic", "show", "curated"]
    assert _cand_is_curated(cand) is True
    vi = VisitItem(
        item_id="probe",
        name=cand["name"],
        city=cand["city"],
        day=3,
        category=cand["category"],
        curated=_cand_is_curated(cand or {}),  # _assemble_plan 装配同式
    )
    assert vi.curated is True
    # 控制组：无 curated 标的行三路全不命中
    plain = _candidate_from_row(
        _row(tags=["intl", "sygic", "show"]), "POINT(108.9430 34.2611)"
    )
    assert _cand_is_curated(plain) is False


def test_final_sweep_keeps_curated_created_and_tier2():
    """终局清算（_drop_untimed_visits，探针命中的发射点）：curated/
    created/tier≤2 王牌不删——原地保留（无时刻）+双语披露；普通 TAG
    卡照旧移除留痕。"""
    curated = _visit(
        "长安十二时辰主题街区", 240, _V, 3, category="citywalk", curated=True
    )
    created = _visit("用户手建点", 60, _GL, 3, created=True)
    ace = _visit("陕西华清宫", 120, _CQ, 3, tier=2)
    plain = _visit("杂点", 60, _VIC, 3)
    timed = _visit("已排点", 60, _BLG, 3, start=time(9, 0))
    d3 = DayPlan(day=3, base_city="西安", items=[timed, curated, created, ace, plain])
    plan = _plan(d3)
    notes = _drop_untimed_visits(plan)
    names = {i.name for i in d3.items}
    assert names == {"已排点", "长安十二时辰主题街区", "用户手建点", "陕西华清宫"}
    assert any("长安十二时辰主题街区" in n and "不删除" in n for n in notes)
    assert any("用户手建点" in n and "手动添加" in n and "不删除" in n for n in notes)
    assert any("名录王牌" in n and "不删除" in n for n in notes)
    assert any("杂点" in n and "已从行程移除" in n for n in notes)


def test_final_sweep_keep_note_dedupes_across_passes():
    """终闸在链上跑两遍（finalize×2）：同卡保留披露同文案去重不重复
    留痕（挪天后文案变了不算重复）。"""
    curated = _visit(
        "长安十二时辰主题街区", 240, _V, 3, category="citywalk", curated=True
    )
    timed = _visit("已排点", 60, _BLG, 3, start=time(9, 0))
    d3 = DayPlan(day=3, base_city="西安", items=[timed, curated])
    plan = _plan(d3)
    notes1 = _drop_untimed_visits(plan)
    assert any("不删除" in n for n in notes1)
    plan.assumptions.extend(notes1)
    notes2 = _drop_untimed_visits(plan)
    assert notes2 == []
    assert any(i is curated for i in d3.items)


def test_read_gate_keeps_curated_dangling():
    """读闸（drop_dangling_visits）同口径：混合日上的 None-None
    curated 卡不删；普通杂卡照旧清。"""
    curated = _visit(
        "长安十二时辰主题街区", 240, _V, 4, category="citywalk", curated=True
    )
    plain = _visit("杂点", 60, _VIC, 4)
    timed = _visit("已排点", 60, _BLG, 4, start=time(9, 0))
    d4 = DayPlan(day=4, base_city="西安", items=[timed, curated, plain])
    plan = _plan(d4)
    notes = drop_dangling_visits(plan)
    names = {i.name for i in d4.items}
    assert "长安十二时辰主题街区" in names
    assert "杂点" not in names
    assert any("不删除" in n for n in notes)


def _leg(day: int = 1, *, to: str = "成都") -> TransferItem:
    return TransferItem(
        item_id=f"t-{day}",
        day=day,
        seq=1,
        mode="train",
        from_city="上海",
        to_city=to,
        start_time=time(8, 0),
        end_time=time(12, 0),
    )


_CD = GeoPoint(lon=104.06, lat=30.66)  # 成都市区
_DJY = GeoPoint(lon=103.62, lat=31.00)  # 都江堰（王牌）
_KD = GeoPoint(lon=102.22, lat=30.05)  # 康定（互远挡宿主）

_TIERS_CD = {
    "青城山—都江堰": 1,
    "金沙遗址博物馆": 11,
    "宽窄巷子": 8,
    "武侯祠": 9,
    "人民公园": 10,
    "成都大熊猫繁育研究基地": 11,
}


def test_transfer_sweep_single_day_keeps_curated():
    """转场日清算删除分支（单日无宿主可挪）：curated 卡不删——原地
    保留+披露。"""
    curated = _visit(
        "长安十二时辰主题街区", 240, _V, 1, category="citywalk", curated=True
    )
    d1 = DayPlan(day=1, base_city="西安", items=[_leg(1, to="西安"), curated])
    plan = _plan(d1)
    notes = _transfer_day_sweep(plan)
    assert any(i is curated for i in d1.items)
    assert curated.day == 1
    assert any("精选库" in n and "不删除" in n for n in notes)


def test_yield_never_ejects_curated_seat():
    """弹座池豁免：满员日唯一可弹件是 curated 卡时不弹（弹出后无宿主
    天=整卡蒸发）——让位失败走清算/披露，curated 卡钉在原座；tier≤2
    王牌同拍保护不删（对照锚 test_transfer_sweep_yields_for_premium：
    普通卡照旧弹出腾座）。"""
    premium = _visit("青城山—都江堰", 180, _DJY, 1, tier=1, city="成都")
    d1 = DayPlan(day=1, base_city="成都", items=[_leg(), premium])
    seat = _visit(
        "金沙遗址博物馆",
        90,
        _CD,
        2,
        tier=11,
        city="成都",
        curated=True,
        start=time(9, 0),
    )
    d2 = DayPlan(
        day=2,
        base_city="成都",
        items=[
            seat,
            _visit(
                "宽窄巷子",
                90,
                _CD,
                2,
                tier=8,
                city="成都",
                pinned=True,
                start=time(13, 30),
            ),
            _visit(
                "武侯祠",
                90,
                GeoPoint(lon=104.05, lat=30.64),
                2,
                tier=9,
                city="成都",
                pinned=True,
                start=time(15, 0),
            ),
            _visit(
                "人民公园",
                90,
                _CD,
                2,
                tier=10,
                city="成都",
                pinned=True,
                start=time(16, 30),
            ),
        ],
    )
    plan = _plan(d1, d2)
    notes = _transfer_day_sweep(plan, frozenset(), dict(_TIERS_CD))
    # curated 座没被弹出（时刻原封）
    assert any(i is seat for i in d2.items)
    assert seat.start_time == time(9, 0)
    assert not any("让位" in n for n in notes)
    # 王牌让位失败也无宿主可挪 → tier≤2 保护：不删
    assert any(i is premium for i in d1.items)
    assert premium.day == 1
    assert any("名录王牌" in n and "不删除" in n for n in notes)


def test_arrival_clash_keeps_created_card():
    """到达日冲突清理删除分支：让位救不回时 created 卡不删——清时刻
    原地保留+披露（tier≤2 仍按原口径移除，锚
    test_eject_restored_when_premium_still_cannot_host 不动）。"""
    mine = _visit("用户手建秘境", 180, _DJY, 1, created=True, city="成都")
    # 早闭馆（13:00）+ 12:00 落地地板：当天物理装不下 → 进搁浅梯
    mine.poi_id = "poi-mine"
    mine.opening_hours = "08:30-13:00"
    d1 = DayPlan(day=1, base_city="成都", items=[_leg(), mine])
    d2 = DayPlan(
        day=2,
        base_city="成都",
        items=[
            _visit(
                "金沙遗址博物馆", 120, _CD, 2, tier=11, city="成都", start=time(9, 0)
            ),
            _visit("宽窄巷子", 90, _KD, 2, tier=8, city="成都", start=time(13, 30)),
            _visit(
                "武侯祠",
                90,
                GeoPoint(lon=104.05, lat=30.64),
                2,
                tier=9,
                city="成都",
                start=time(15, 0),
            ),
            _visit(
                "成都大熊猫繁育研究基地",
                120,
                GeoPoint(lon=104.15, lat=30.74),
                2,
                tier=11,
                city="成都",
                pinned=True,
                start=time(8, 0),
            ),
        ],
    )
    plan = _plan(d1, d2)
    tiers = dict(_TIERS_CD)
    tiers["用户手建秘境"] = 1
    notes = _reconcile_transfer_days(plan, tier_by_name=tiers)
    assert any(i is mine for i in d1.items)
    assert any("手动添加" in n and "不删除" in n for n in notes)
    assert not any(mine.name in n and "已从行程移除" in n for n in notes)


# ------------------------------------------- 11-09 终装日纯度清扫（双案根修）

_JEQ = GeoPoint(lon=108.9725, lat=34.2192)  # 十二时辰街区（大雁塔簇内 ~0.6km）
_YXF = GeoPoint(lon=108.9653, lat=34.2672)  # 永兴坊（市区东侧 ~2.4km 于钟楼）


def test_day_purity_sweep_purges_far_from_arrival_day():
    """清扫①：出圈远点（>15km 于城心 medoid）落到达日必挪非到达日
    （11-09 兵马俑/骊山到达日案——「到达日只适合简单 CITYWALK 或
    SHOW」硬口径）。"""
    lishan = _visit("临潼骊山风景名胜区", 120, _LISHAN, 1, tier=9)
    d1 = DayPlan(
        day=1,
        base_city="西安",
        items=[_visit("西安大唐西市博物馆", 60, _V, 1, tier=11), lishan],
    )
    d2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            _visit("西安鼓楼", 40, _GL, 2, tier=3),
            _visit("西安城墙", 60, _CQ, 2, tier=3),
        ],
    )
    d3 = DayPlan(
        day=3,
        base_city="西安",
        items=[
            _visit("西安钟楼", 40, _GL, 3, tier=3),
            _visit("大唐西市", 60, _V, 3, tier=11),
        ],
    )
    plan = _plan(d1, d2, d3)
    _day_purity_sweep(plan, frozenset())
    assert any(i is lishan for i in d2.items)
    assert lishan.day == 2
    assert any("距市区较远" in str(a) for a in plan.assumptions)


def test_day_purity_sweep_does_not_move_far_arrival_card_to_return_day():
    far = _visit("远郊参访", 120, _LISHAN, 1, tier=9)
    d1 = DayPlan(
        day=1,
        base_city="西安",
        items=[_visit("市区小点", 60, _V, 1, tier=11), far],
    )
    d2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            _visit("中段一", 40, _GL, 2, tier=3),
            _visit("中段二", 60, _CQ, 2, tier=3),
        ],
    )
    d3 = DayPlan(
        day=3,
        base_city="西安",
        items=[
            _visit("末日一", 40, _GL, 3, tier=3),
            _visit("末日二", 60, _CQ, 3, tier=3),
        ],
    )
    plan = _plan(d1, d2, d3)
    _day_purity_sweep(plan, frozenset())
    assert far.day == 2
    assert any(i is far for i in d2.items)
    assert not any(i is far for i in d3.items)


def test_day_purity_sweep_reunites_family_on_show_day():
    """清扫③：出圈族散件并回坐族内演出的日（华清宫并回兵马俑+
    《秦俑情》日——11-09 临潼拆族案，演出贴场馆族=族锚）。"""
    hqg = _visit("华清宫", 120, _HQG, 2, tier=2)
    qyq = _visit(
        "《秦俑情》", 80, _BMY, 4, category="entertainment", tier=6, start=time(17, 0)
    )
    bmy = _visit("秦始皇帝陵博物院", 180, _BMY, 4, tier=1)
    # 城心点须 ≥ 临潼票数，否则小夹具 medoid 会落临潼侧（票制锚）
    d1 = DayPlan(
        day=1,
        base_city="西安",
        items=[
            _visit("西安大唐西市博物馆", 60, _V, 1, tier=11),
            _visit("西安钟楼", 40, _GL, 1, tier=3),
            _visit("西安城墙", 60, _CQ, 1, tier=3),
        ],
    )
    d2 = DayPlan(
        day=2,
        base_city="西安",
        items=[_visit("西安鼓楼", 40, _GL, 2, tier=3), hqg],
    )
    d4 = DayPlan(day=4, base_city="西安", items=[bmy, qyq])
    d5 = DayPlan(day=5, base_city="西安", items=[])
    plan = _plan(d1, d2, d4, d5)
    _day_purity_sweep(plan, frozenset())
    assert any(i is hqg for i in d4.items)
    assert hqg.day == 4


def test_day_purity_sweep_retimes_movable_family_show():
    hqg = _visit("华清宫", 120, _HQG, 2, tier=2)
    qyq = _visit(
        "《秦俑情》", 80, _BMY, 4, category="entertainment", tier=6, start=time(11, 0)
    )
    qyq.opening_hours = "多场（约11:00/17:00，以当日公告为准）"
    bmy = _visit("秦始皇帝陵博物院", 180, _BMY, 4, tier=1)
    d1 = DayPlan(
        day=1,
        base_city="西安",
        items=[
            _visit("西安大唐西市博物馆", 60, _V, 1, tier=11),
            _visit("西安钟楼", 40, _GL, 1, tier=3),
            _visit("西安城墙", 60, _CQ, 1, tier=3),
        ],
    )
    d2 = DayPlan(
        day=2,
        base_city="西安",
        items=[_visit("西安鼓楼", 40, _GL, 2, tier=3), hqg],
    )
    d4 = DayPlan(day=4, base_city="西安", items=[bmy, qyq])
    d5 = DayPlan(day=5, base_city="西安", items=[])
    plan = _plan(d1, d2, d4, d5)
    _day_purity_sweep(plan, frozenset())
    assert any(i is hqg for i in d4.items)
    assert hqg.start_time is not None
    assert bmy.start_time is not None
    assert qyq.start_time == time(17, 0)


def test_day_purity_sweep_failed_family_merge_rolls_back_whole_family(monkeypatch):
    import app.services.agent.plan as plan_mod

    first = _visit("远族散件一", 120, _HQG, 2, tier=2, start=time(9, 0))
    second = _visit("远族散件二", 120, _LISHAN, 2, tier=2, start=time(13, 0))
    show = _visit(
        "远区多场演出",
        80,
        _BMY,
        4,
        category="entertainment",
        tier=6,
        start=time(11, 0),
    )
    show.opening_hours = "多场（约11:00/17:00，以当日公告为准）"
    anchor_visit = _visit("远区锚点", 180, _BMY, 4, tier=1, start=time(9, 0))
    d1 = DayPlan(
        day=1,
        base_city="西安",
        items=[
            _visit("城件一", 60, _V, 1, tier=11, start=time(9, 0)),
            _visit("城件二", 40, _GL, 1, tier=3, start=time(11, 0)),
            _visit("城件三", 60, _CQ, 1, tier=3, start=time(13, 0)),
        ],
    )
    d2 = DayPlan(day=2, base_city="西安", items=[first, second])
    d4 = DayPlan(day=4, base_city="西安", items=[anchor_visit, show])
    d5 = DayPlan(day=5, base_city="西安", items=[])
    plan = _plan(d1, d2, d4, d5)
    real_sequence = plan_mod._fallback_sequence_times

    def leave_one_family_member_untimed(p):
        real_sequence(p)
        second.start_time = None
        second.end_time = None

    monkeypatch.setattr(
        plan_mod, "_fallback_sequence_times", leave_one_family_member_untimed
    )
    _day_purity_sweep(plan, frozenset())

    assert all(any(i is v for i in d2.items) for v in (first, second))
    assert all(all(i is not v for i in d4.items) for v in (first, second))
    assert first.day == second.day == 2
    assert show.start_time == time(11, 0)
    assert any("保留原日安排" in str(a) for a in plan.assumptions)


def test_day_purity_sweep_moves_stranger_out_of_cluster_day():
    """清扫②：大雁塔簇日（t1 簇核+citywalk 伴）里 >5km 独件挪去有
    近簇伴的日（11-09 大清真寺插大雁塔/十二时辰日案——t1/t2 王牌计
    簇核但永不作陌生人候选）。"""
    dzj = _visit("西安大清真寺", 60, _GL, 2, tier=4)
    dyt = _visit("大雁塔大唐芙蓉园景区", 120, _DYT, 2, tier=1)
    jeq = _visit("长安十二时辰主题街区", 90, _JEQ, 2, category="citywalk", tier=3)
    d1 = DayPlan(
        day=1,
        base_city="西安",
        items=[_visit("西安大唐西市博物馆", 60, _V, 1, tier=11)],
    )
    d2 = DayPlan(day=2, base_city="西安", items=[dyt, jeq, dzj])
    d3 = DayPlan(
        day=3,
        base_city="西安",
        items=[
            _visit("西安钟楼", 40, _GL, 3, tier=3),
            _visit("西安城墙", 60, _CQ, 3, tier=3),
        ],
    )
    plan = _plan(d1, d2, d3)
    _day_purity_sweep(plan, frozenset())
    assert any(i is dzj for i in d3.items)
    assert dzj.day == 3
    assert any(i is dyt for i in d2.items) and any(i is jeq for i in d2.items)


def test_day_purity_sweep_family_day_city_stranger_freed_then_merge():
    """清扫②+③联动（11-09 拆族二拍实录）：D4 被市内弱件（永兴坊）占
    位 + 族演（《秦俑情》）在册、华清宫拆在 D5——族占日市内件先回城
    腾位，族散件随后并回锚日。"""
    yxf = _visit("永兴坊", 90, _YXF, 4, tier=4)
    hqg = _visit("华清宫", 120, _HQG, 5, tier=2)
    qyq = _visit(
        "《秦俑情》", 80, _BMY, 4, category="entertainment", tier=6, start=time(17, 0)
    )
    bmy = _visit("秦始皇帝陵博物院", 180, _BMY, 4, tier=1)
    d1 = DayPlan(
        day=1,
        base_city="西安",
        items=[
            _visit("西安大唐西市博物馆", 60, _V, 1, tier=11),
            _visit("西安钟楼", 40, _GL, 1, tier=3),
            _visit("西安城墙", 60, _CQ, 1, tier=3),
        ],
    )
    d3 = DayPlan(
        day=3,
        base_city="西安",
        items=[_visit("西安鼓楼", 40, _GL, 3, tier=3)],
    )
    d4 = DayPlan(day=4, base_city="西安", items=[bmy, qyq, yxf])
    d5 = DayPlan(day=5, base_city="西安", items=[hqg])
    plan = _plan(d1, d3, d4, d5)
    _day_purity_sweep(plan, frozenset())
    assert any(i is yxf for i in d3.items)  # 族日占位者回城（鼓楼近簇伴日）
    assert not any(i is yxf for i in d4.items)
    assert any(i is hqg for i in d4.items)  # 族散件腾位后并回锚日
    assert hqg.day == 4
    assert any("已挪至第3天" in str(a) for a in plan.assumptions)
    assert any("已合并至第4天" in str(a) for a in plan.assumptions)


def test_day_purity_sweep_ignores_arrival_card_already_dropped():
    orphan = _visit("到达远件", 180, _LISHAN, 1, tier=9)
    d1 = DayPlan(
        day=1,
        base_city="西安",
        items=[
            _visit("城件一", 60, _V, 1, tier=11),
            _visit("城件二", 60, _GL, 1, tier=3),
            _visit("城件三", 60, _CQ, 1, tier=3),
            orphan,
        ],
    )
    d3 = DayPlan(
        day=3,
        base_city="西安",
        items=[
            _visit("收容件一", 200, _V, 3, tier=3),
            _visit("收容件二", 200, _GL, 3, tier=3),
            _visit("收容件三", 200, _CQ, 3, tier=3),
        ],
    )
    show = _visit(
        "远区演出", 80, _BMY, 4, category="entertainment", tier=6, start=time(17, 0)
    )
    city_stranger = _visit("待挪城件", 40, _GL, 4, tier=4)
    d4 = DayPlan(
        day=4,
        base_city="西安",
        items=[
            _visit("远区主件", 180, _BMY, 4, tier=1),
            show,
            city_stranger,
            _visit("留守城件", 40, _CQ, 4, tier=4),
        ],
    )
    plan = _plan(d1, d3, d4)
    _day_purity_sweep(plan, frozenset())
    assert all(orphan not in d.items for d in plan.days)
    assert any(
        orphan.name in str(a) and "本次未排入" in str(a) for a in plan.assumptions
    )
