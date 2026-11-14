# -*- coding: utf-8 -*-
"""端点日轻量终装清扫锚·到达日侧（2026-11-11 拍板「到达日与离城日
同原则」+「排程顺序」拍板：雨日→到达日→正常日→离城日）。

单卡引擎无上游守卫——选层溢出/让位弹座/紧族重逢/全局换座各相位
各自合规，合力可把重磅卡塞进到达日。终装清扫按「简单街区卡」口径（
_arrival_simple_visit 唯一定义点：街道/citywalk 类且非主题街区演出块
且 ≤120min 且非 tier≤2 王牌）对账：

① 重磅出到达日（tier≤2/主题街区块/>80min 大块；整族轻量形态豁免——
   到达日整族落位通道终装镜像；钉/软钉不动=铁律 19；curated 只挪不删，
   有宿主同样挪；无宿主=保留+披露，只挪不删）
② 空日留白披露（11-11 拍板「不强行从其它日期挪卡」：到达日没收到
   简单街区卡/SHOW 就不安排节目，接受空日——轻卡落位靠排程顺序自然
   发生，本清扫绝不跨日挪卡补；从别日硬挪=既违拍板又把源日拆散）
③ 一项上限（11-12 拍板「到达日与离城日只安排一项离酒店近的游览
   即可；没有酒店地址则以市中心为默认」）：>1 张只留距锚最近一张，
   余卡挪非端点日（只挪不删；无宿主=保留+披露；钉/软钉不动=铁律
   19；演出/餐宿不计入；不可核即不拦）

返程日分支锚见 test_return_day_light.py。
"""

from datetime import time

from app.services.agent.plan import (
    _arrival_heavy_visit,
    _arrival_simple_visit,
    _endpoint_day_light_sweep,
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


def test_heavy_evicted_and_no_recruit_accept_empty():
    """① 出+② 留白拍板：王牌出到达日落有容量日；街卡**不跨日挪补**
    （留在第 3 天）；≤80min 小馆留守（收轻内容口径）；到达日无简卡
    =留白披露（11-11「不强行从其它日期挪卡」）。③ 一项上限（11-12）
    同案收口：第 3 天为离城日持两张（街卡+小馆）→小馆为远者挪第 2 天，
    只留街卡一张。"""
    ace = _v("王牌A", 120, _C0, 1, tier=1)
    # 小馆放远点（>1km）：避免与王牌凑成整族轻量形态触发①豁免
    small = _v("小馆", 60, _D3A, 1, tier=9)
    b = _v("馆B", 60, _D2A, 2, tier=9)
    c = _v("馆C", 60, _D2B, 2, tier=9)
    st = _v("样本坊", 90, _ST, 3, tier=4)
    dd = _v("馆D", 60, _D3A, 3, tier=9)
    plan = _plan(_d(1, ace, small), _d(2, b, c), _d(3, st, dd))
    _endpoint_day_light_sweep(plan, frozenset())
    assert _day_of(plan, ace) == 2
    assert _day_of(plan, small) == 1
    # 绝不跨日挪卡补：街卡留在原地（③ 只出多余一张，不招卡）
    assert _day_of(plan, st) == 3
    # ③ 一项上限：离城日两张→远者（馆D）挪走，只留街卡
    assert _day_of(plan, dd) == 2
    assert any("只安排一项" in a and "馆D" in a for a in plan.assumptions)
    # 2026-11-13 六拍：到达日还有小馆=不是「整天没安排」，不补自由漫步
    # 占位、也不出「留白」披露（占位只在真的空日才补）。
    assert not any(i.item_id.startswith("citywalk-ph-d") for i in plan.days[0].items)
    assert not any("留白" in a for a in plan.assumptions)
    # 挪动后全部排上时刻（「？」卡不许出自本清扫）
    for d in plan.days:
        for i in d.items:
            assert i.start_time is not None, f"{i.name} 排不上时刻"


def test_heavy_removed_to_unplaced_when_no_host():
    """11-13 第三拍：无宿主=移除出行程落 unplaced（端点日绝不留重磅/
    远郊卡）+ 披露加回路径；他日满员不得硬塞，也不得「暂保留」在到达日。"""
    ace = _v("王牌A", 120, _C0, 1, tier=1)
    full = [_v(f"满员{k}", 100, _D2A, 2, tier=9) for k in range(4)]
    # 2026-11-13 起两天窗两端都是端点日（到达+返程）——「全端点日」不变形，
    # 违例重磅滞留合法；「无宿主出卡」须 3 天窗：day2=正常宿主日（满员），
    # day3=空返程日。
    plan = _plan(_d(1, ace), _d(2, *full), _d(3))
    _endpoint_day_light_sweep(plan, frozenset())
    assert all(not any(i is ace for i in d.items) for d in plan.days), (
        "违例重磅卡不得滞留到达日"
    )
    chip = next((u for u in plan.unplaced if (u.poi_id or u.name) == ace.name), None)
    assert chip is not None and chip.reason == "endpoint_stay"
    assert any("王牌A" in a and "已从行程移除" in a for a in plan.assumptions)


def test_heavy_kept_and_disclosed_when_no_host_curated():
    """curated 卡永不删：无宿主同样保留+披露（第三拍移除只适用于普通卡）。"""
    ace = _v("王牌A", 120, _C0, 1, tier=1, curated=True)
    full = [_v(f"满员{k}", 100, _D2A, 2, tier=9) for k in range(4)]
    plan = _plan(_d(1, ace), _d(2, *full))
    _endpoint_day_light_sweep(plan, frozenset())
    assert _day_of(plan, ace) == 1
    assert any("王牌A" in a and "暂保留" in a for a in plan.assumptions)


def test_theme_block_treated_heavy_and_evicted():
    """名带「街区」的 240min 沉浸块=重磅（非简单 CITYWALK），出到达日。"""
    blk = _v("沉浸主题街区", 240, _ST, 1, category="citywalk", tier=3)
    small = _v("小馆", 60, _C1, 1, tier=9)
    b = _v("馆B", 50, _D2A, 2, tier=9)
    c = _v("馆C", 50, _D2B, 2, tier=9)
    dd = _v("馆D", 60, _D3A, 3, tier=9)
    plan = _plan(_d(1, blk, small), _d(2, b, c), _d(3, dd))
    _endpoint_day_light_sweep(plan, frozenset())
    assert _day_of(plan, blk) == 2
    assert _day_of(plan, small) == 1


def test_compact_family_day_exempt_from_heavy_eviction_but_capped_to_one():
    """① 族豁免不变（族员不算重磅、不触发①出——无「重磅」挪卡披露）；
    ③ 一项上限（11-12 拍板「到达日只安排一项」）照样收口：只留距锚
    最近的一员（族锚 _F1=锚点本身 0km），余员挪非端点日。两张相邻
    小卡同样是「两项」，族形态不豁免本闸（11-11 族豁免只管「算不算
    重磅」，11-12 闸管「留几张」）。"""
    a1 = _v("族锚", 90, _F1, 1, tier=2)
    a2 = _v("族伴甲", 40, _F2, 1, tier=9)
    a3 = _v("族伴乙", 40, _F3, 1, tier=9)
    b = _v("馆B", 60, _D2A, 2, tier=9)
    c = _v("馆C", 60, _D2B, 2, tier=9)
    st = _v("尾坊", 90, _ST, 3, tier=4)
    plan = _plan(_d(1, a1, a2, a3), _d(2, b, c), _d(3, st))
    _endpoint_day_light_sweep(plan, frozenset())
    # ① 不当作重磅逐出（族豁免仍在案）
    assert not any("重磅" in x for x in plan.assumptions)
    # ③ 只留一项：恰一员留守到达日，另两名挪去第 2 天
    fam = (a1, a2, a3)
    assert sum(1 for i in plan.days[0].items if any(i is f for f in fam)) == 1
    assert sum(1 for i in plan.days[1].items if any(i is f for f in fam)) == 2
    assert any("只安排一项" in x for x in plan.assumptions)


def test_pinned_heavy_untouched():
    """钉住重磅=用户权威（铁律 19），清扫不动。"""
    ace = _v("王牌A", 120, _C0, 1, tier=1, pinned=True)
    b = _v("馆B", 60, _D2A, 2, tier=9)
    c = _v("馆C", 60, _D2B, 2, tier=9)
    plan = _plan(_d(1, ace), _d(2, b, c))
    _endpoint_day_light_sweep(plan, frozenset())
    assert _day_of(plan, ace) == 1
    assert ace.pinned is True


def test_curated_theme_block_stays_when_all_days_endpoint():
    """11-13 双向同闸锚：2 天单城行程 day1=到达日、day2=离城日镜像——
    两天都是端点日，240min 主题块无合法宿主（端点日之间不互搬=违规搬
    家），curated 只挪不删下=原天保留+披露（「其余各天排不下」口径）。"""
    blk = _v("沉浸主题街区", 240, _ST, 1, category="citywalk", tier=3, curated=True)
    small = _v("小馆", 60, _C1, 1, tier=9)
    b = _v("馆B", 50, _D2A, 2, tier=9)
    c = _v("馆C", 50, _D2B, 2, tier=9)
    plan = _plan(_d(1, blk, small), _d(2, b, c))
    _endpoint_day_light_sweep(plan, frozenset())
    assert _day_of(plan, blk) == 1
    assert blk.curated is True
    assert any("沉浸主题街区" in x and "暂保留" in x for x in plan.assumptions)


# ------------------------------------------------------- ③ 一项上限（11-12）


def test_arrival_day_capped_to_one_keeps_anchor_nearest():
    """11-12 拍板锚·到达日侧：两张散卡（近坊+远馆）只留距锚最近一张，
    另一张挪非端点日；披露在案。无酒店→城心锚为市中心默认。"""
    near = _v("近坊", 90, _ST, 1, tier=4)
    far = _v("远馆", 60, _D3A, 1, tier=9)
    b = _v("馆B", 60, _D2A, 2, tier=9)
    c = _v("馆C", 60, _D2B, 2, tier=9)
    st = _v("尾坊", 90, _ST, 3, tier=4)
    plan = _plan(_d(1, near, far), _d(2, b, c), _d(3, st))
    _endpoint_day_light_sweep(plan, frozenset())
    assert _day_of(plan, near) == 1
    assert _day_of(plan, far) == 2
    assert any("只安排一项" in x and "远馆" in x for x in plan.assumptions)


def test_arrival_day_cap_keeps_pinned_extra():
    """余卡钉住=铁律 19：上限闸不挪钉卡（当日仍两张=用户权威，无披露）。"""
    near = _v("近坊", 90, _ST, 1, tier=4)
    far = _v("远馆", 60, _D3A, 1, tier=9, pinned=True)
    b = _v("馆B", 60, _D2A, 2, tier=9)
    c = _v("馆C", 60, _D2B, 2, tier=9)
    st = _v("尾坊", 90, _ST, 3, tier=4)
    plan = _plan(_d(1, near, far), _d(2, b, c), _d(3, st))
    _endpoint_day_light_sweep(plan, frozenset())
    assert _day_of(plan, near) == 1
    assert _day_of(plan, far) == 1
    assert far.pinned is True
    assert not any("只安排一项" in x for x in plan.assumptions)


def test_no_recruit_accept_empty_arrival_day():
    """11-11 拍板锚：到达日没收到简单街区卡时**绝不从别日挪卡补**（哪怕
    源日有现成街卡、哪怕有营业窗空档）；11-13 六拍补充：只有**完全没有
    参访件**的到达日才补「城市漫步（自由安排）」占位（见
    tests/test_arrival_day_fill.py），有小馆的日子不算空日。"""
    small = _v("小馆", 60, _D3A, 1, tier=9)
    small.poi_id = "p-x"
    small.opening_hours = "10:30-17:00"
    small.start_time = time(9, 30)
    st = _v("样本坊", 60, _ST, 2, tier=4)
    st.poi_id = "p-y"
    st.opening_hours = "09:30-10:30"
    dd = _v("馆D", 60, _D3A, 2, tier=9)
    plan = _plan(_d(1, small), _d(2, st, dd))
    _endpoint_day_light_sweep(plan, frozenset())
    # 街卡原地不动（此前的「升格整日重排挪入」机制已按拍板拆除）
    assert _day_of(plan, st) == 2
    assert _day_of(plan, small) == 1
    # 11-13 六拍：到达日有小馆=已有安排，不补自由漫步占位、不跨日挪卡
    assert not any(i.item_id.startswith("citywalk-ph-d") for i in plan.days[0].items)
