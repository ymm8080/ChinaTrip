# -*- coding: utf-8 -*-
"""到达日轻量终装清扫锚（2026-11-11 拍板「到达日只收简单 CITYWALK/
街区轻件，重磅与长块殿后」）。

单卡引擎无上游守卫——选层溢出/让位弹座/紧族重逢/全局换座各相位
各自合规，合力可把重磅卡塞进到达日，或让到达日一张简单街区卡都拿不到
（重磅占日+下午单大点跳街区实录）。终装清扫按「简单街区卡」口径（
_arrival_simple_visit 唯一定义点：街道/citywalk 类且非主题街区演出块
且 ≤120min 且非 tier≤2 王牌）双向对账：

① 重磅出到达日（tier≤2/主题街区块/>80min 大块；整族轻量形态豁免——
   到达日整族落位通道终装镜像；钉/软钉不动=铁律 19；curated 只挪不删，
   有宿主同样挪；无宿主=保留+披露，只挪不删）
② 简卡进到达日（真到达日无简卡时从同城非到达日挪入一张；挪后两日均
   重排，排不上时刻=整步回滚换披露——「？」卡不许出自本清扫）
"""

from datetime import time

from app.services.agent.plan import (
    _arrival_day_light_sweep,
    _arrival_heavy_visit,
    _arrival_simple_visit,
)
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    VisitItem,
)

# 全城布点：城心簇（互相 ≤2km）+ 第二日簇 + 远点拉开
_C0 = GeoPoint(lon=108.9400, lat=34.2600)  # 城心锚
_C1 = GeoPoint(lon=108.9410, lat=34.2605)  # 城心伴 ~0.1km
_ST = GeoPoint(lon=108.9450, lat=34.2610)  # 街区语素卡 ~0.5km
_D2A = GeoPoint(lon=108.9500, lat=34.2650)  # 第二日伴 A ~1.1km
_D2B = GeoPoint(lon=108.9510, lat=34.2655)  # 第二日伴 B ~1.2km
_D3A = GeoPoint(lon=108.9600, lat=34.2700)  # 远点 ~2.3km
_F1 = GeoPoint(lon=108.9420, lat=34.2590)  # 整族锚
_F2 = GeoPoint(lon=108.9425, lat=34.2592)  # 整族伴甲 ~0.05km
_F3 = GeoPoint(lon=108.9422, lat=34.2588)  # 整族伴乙 ~0.03km


def _v(
    name: str,
    dur: int,
    loc: GeoPoint | None,
    day: int,
    *,
    category: str = "sight",
    tier: int | None = None,
    pinned: bool = False,
    curated: bool = False,
    poi_id: str | None = None,
    opening_hours: str | None = None,
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
        curated=curated,
        poi_id=poi_id,
        opening_hours=opening_hours,
        start_time=start,
        end_time=None,
    )


def _d(day: int, *items) -> DayPlan:
    return DayPlan(day=day, base_city="西安", items=list(items))


def _plan(*days: DayPlan) -> ItineraryPlan:
    return ItineraryPlan(
        itinerary_id="it-arrival-light", cities=["西安"], days=list(days)
    )


def _day_of(plan: ItineraryPlan, v: VisitItem) -> int:
    for d in plan.days:
        if any(i is v for i in d.items):
            return d.day
    raise AssertionError(f"{v.name} 不在任何一天")


# ------------------------------------------------------- 口径谓词（类级单元）


def test_simple_visit_predicate_class_level():
    """简单街区卡口径：街区语素/tier/时长/主题块四闸齐全。"""
    assert _arrival_simple_visit(_v("样本坊", 90, _ST, 1, tier=4)) is True
    # tier≤2 王牌不作简单卡
    assert _arrival_simple_visit(_v("王牌街", 90, _ST, 1, tier=2)) is False
    # 主题街区长块（名含「街区」+citywalk 类）=非简单卡
    assert (
        _arrival_simple_visit(
            _v("沉浸主题街区", 240, _ST, 1, category="citywalk", tier=3)
        )
        is False
    )
    # 超长街区件（>120min）=非简单卡
    assert _arrival_simple_visit(_v("超长古街", 150, _ST, 1, tier=4)) is False
    # 非街区小型馆=非简单卡
    assert _arrival_simple_visit(_v("小馆", 60, _C0, 1, tier=9)) is False


def test_heavy_visit_predicate_class_level():
    """重磅卡口径收窄版：王牌/主题块/>80min 大块；≤80min 小点不算。"""
    assert _arrival_heavy_visit(_v("王牌A", 120, _C0, 1, tier=1)) is True
    assert (
        _arrival_heavy_visit(
            _v("沉浸主题街区", 240, _ST, 1, category="citywalk", tier=3)
        )
        is True
    )
    assert _arrival_heavy_visit(_v("大馆", 120, _C0, 1, tier=5)) is True
    assert _arrival_heavy_visit(_v("小馆", 60, _C0, 1, tier=9)) is False
    assert _arrival_heavy_visit(_v("样本坊", 90, _ST, 1, tier=4)) is False


# ------------------------------------------------------- 清扫行为锚


def test_heavy_evicted_and_simple_recruited():
    """①+②双向对账：王牌出到达日落有容量日；到达日拿到街区简卡；
    ≤80min 小馆留守（收轻内容口径）。"""
    ace = _v("王牌A", 120, _C0, 1, tier=1)
    # 小馆放远点（>1km）：避免与王牌凑成整族轻量形态触发①豁免
    small = _v("小馆", 60, _D3A, 1, tier=9)
    b = _v("馆B", 60, _D2A, 2, tier=9)
    c = _v("馆C", 60, _D2B, 2, tier=9)
    st = _v("样本坊", 90, _ST, 3, tier=4)
    dd = _v("馆D", 60, _D3A, 3, tier=9)
    plan = _plan(_d(1, ace, small), _d(2, b, c), _d(3, st, dd))
    _arrival_day_light_sweep(plan, frozenset())
    assert _day_of(plan, ace) == 2
    assert _day_of(plan, small) == 1
    assert _day_of(plan, st) == 1
    assert _day_of(plan, dd) == 3
    # 挪动后全部排上时刻（「？」卡不许出自本清扫）
    for d in plan.days:
        for i in d.items:
            assert i.start_time is not None, f"{i.name} 排不上时刻"


def test_heavy_kept_and_disclosed_when_no_host():
    """无宿主=保留+披露（只挪不删）；他日满员不得硬塞。"""
    ace = _v("王牌A", 120, _C0, 1, tier=1)
    full = [_v(f"满员{k}", 100, _D2A, 2, tier=9) for k in range(4)]
    plan = _plan(_d(1, ace), _d(2, *full))
    _arrival_day_light_sweep(plan, frozenset())
    assert _day_of(plan, ace) == 1
    assert any("王牌A" in a for a in plan.assumptions)


def test_theme_block_treated_heavy_and_evicted():
    """名带「街区」的 240min 沉浸块=重磅（非简单 CITYWALK），出到达日。"""
    blk = _v("沉浸主题街区", 240, _ST, 1, category="citywalk", tier=3)
    small = _v("小馆", 60, _C1, 1, tier=9)
    b = _v("馆B", 50, _D2A, 2, tier=9)
    c = _v("馆C", 50, _D2B, 2, tier=9)
    dd = _v("馆D", 60, _D3A, 3, tier=9)
    plan = _plan(_d(1, blk, small), _d(2, b, c), _d(3, dd))
    _arrival_day_light_sweep(plan, frozenset())
    assert _day_of(plan, blk) == 2
    assert _day_of(plan, small) == 1


def test_compact_family_day_exempt_from_eviction():
    """整族轻量形态（≥2 员、每员 ≤120min、合计 ≤180min、两两全连通
    ≤1km）豁免①——到达日整族落位通道终装镜像，拆族比留重磅更伤。"""
    a1 = _v("族锚", 90, _F1, 1, tier=2)
    a2 = _v("族伴甲", 40, _F2, 1, tier=9)
    a3 = _v("族伴乙", 40, _F3, 1, tier=9)
    st = _v("样本坊", 90, _ST, 2, tier=4)
    dd = _v("馆D", 60, _D3A, 2, tier=9)
    plan = _plan(_d(1, a1, a2, a3), _d(2, st, dd))
    _arrival_day_light_sweep(plan, frozenset())
    assert _day_of(plan, a1) == 1
    assert _day_of(plan, a2) == 1
    assert _day_of(plan, a3) == 1


def test_pinned_heavy_untouched():
    """钉住重磅=用户权威（铁律 19），清扫不动。"""
    ace = _v("王牌A", 120, _C0, 1, tier=1, pinned=True)
    b = _v("馆B", 60, _D2A, 2, tier=9)
    c = _v("馆C", 60, _D2B, 2, tier=9)
    plan = _plan(_d(1, ace), _d(2, b, c))
    _arrival_day_light_sweep(plan, frozenset())
    assert _day_of(plan, ace) == 1
    assert ace.pinned is True


def test_curated_theme_block_evicted_when_host_exists():
    """curated 只挪不删（永不进删除闸不受影响）——有宿主同样出到达日。"""
    blk = _v("沉浸主题街区", 240, _ST, 1, category="citywalk", tier=3, curated=True)
    small = _v("小馆", 60, _C1, 1, tier=9)
    b = _v("馆B", 50, _D2A, 2, tier=9)
    c = _v("馆C", 50, _D2B, 2, tier=9)
    plan = _plan(_d(1, blk, small), _d(2, b, c))
    _arrival_day_light_sweep(plan, frozenset())
    assert _day_of(plan, blk) == 2
    assert blk.curated is True


def test_recruit_escalates_to_whole_day_rebuild():
    """直落落不下（街区卡唯一营业窗被既有卡占住）→ 升格整日重排：
    可清卡清时重建后两卡均排上时刻；仍排不上才整步回滚换披露。"""
    small = _v("小馆", 60, _D3A, 1, tier=9)
    small.poi_id = "p-x"
    small.opening_hours = "10:30-17:00"
    small.start_time = time(9, 30)  # 直落期占住 09:30-10:30 唯一档
    st = _v("样本坊", 60, _ST, 2, tier=4)
    st.poi_id = "p-y"
    st.opening_hours = "09:30-10:30"  # 唯一可行营业档
    dd = _v("馆D", 60, _D3A, 2, tier=9)
    plan = _plan(_d(1, small), _d(2, st, dd))
    _arrival_day_light_sweep(plan, frozenset())
    assert _day_of(plan, st) == 1
    assert st.start_time is not None
    assert _day_of(plan, small) == 1
    assert small.start_time is not None
