# -*- coding: utf-8 -*-
"""端点日轻量终装清扫锚·返程日侧（2026-11-11 拍板「到达日与离城日
同原则」）：与 11-05 轻量保底/11-08 市区圈四层闸同口径不双挪——那些
闸管上游准入与保位，本清扫只做终装对账。返程日侧两拍：

① 违例出返程日（11-13 拍板「出发日和到达日一样」双向同闸 _stay_out）：
   重磅翼 >80min 非街卡=「不能安排大景点时间」；远翼距酒店或城心锚
   >_EP_LIGHT_KM=8km（双锚皆核，收紧自 11-08 的 15km 城心单锚——
   用户根案：距城心 6km 但距酒店 11km 被判「远郊区」=AND 语义）；挪
   同城非端点日（_host_day_for_visit 实位探针终审）；无宿主=保留+披
   露（软放兜底同 11-08「排得上优先于排得轻」——距离闸优先于安排：
   挪得动才挪）。缺坐标/双锚皆缺不拦（「不可核即不拦」11-08 口径）。
② 空日留白披露（同到达日口径）：没收到简单街区卡/SHOW 就留白披露，
   接受离城日无站点安排——绝不跨日挪卡补（11-11「不强行从其它日期
   挪卡」）。
③ 一项上限（11-12 拍板「到达日与离城日只安排一项离酒店近的游览
   即可；没有酒店地址则以市中心为默认」，用户根案「出发日安排了
   两项」）：>1 张只留距锚最近一张（锚=酒店卡，缺则城心锚），余卡
   挪非端点日（只挪不删；无宿主=保留+披露；钉/软钉不动；演出/餐宿
   不计入；不可核即不拦）。
"""

from datetime import time

from app.services.agent.plan import _endpoint_day_light_sweep
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    TransferItem,
    VisitItem,
)

# 全城布点：城心簇（互相 ≤2km）+ 出圈远点（>15km，11-08 口径贴 15km
# 片区圈——街道类样本离城心锚 ~12km 在圈内、远郊件 27km 出圈）
_C0 = GeoPoint(lon=108.9400, lat=34.2600)  # 城心锚
_C1 = GeoPoint(lon=108.9410, lat=34.2605)  # 城心伴 ~0.1km
_ST = GeoPoint(lon=108.9450, lat=34.2610)  # 街区语素卡 ~0.5km
_D2A = GeoPoint(lon=108.9500, lat=34.2650)  # 第二日伴 A ~1.1km
_D2B = GeoPoint(lon=108.9510, lat=34.2655)  # 第二日伴 B ~1.2km
_FAR = GeoPoint(lon=109.2400, lat=34.2600)  # 出圈远点 ~27km
_MID = GeoPoint(lon=108.9550, lat=34.2680)  # 圈内中距 ~1.6km（①不挪③收）
_EDGE = GeoPoint(lon=108.9850, lat=34.2450)  # 圈内边缘 ~5km（①不挪③收）
_HOTEL_FAR = GeoPoint(lon=109.0400, lat=34.2600)  # 远酒店 ~9.3km（11-13 双锚锚）


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
        start_time=None,
        end_time=None,
    )


def _d(day: int, *items) -> DayPlan:
    return DayPlan(day=day, base_city="西安", items=list(items))


def _plan(*days: DayPlan, cities=("西安",)) -> ItineraryPlan:
    return ItineraryPlan(
        itinerary_id="it-return-light", cities=list(cities), days=list(days)
    )


def _day_of(plan: ItineraryPlan, v: VisitItem) -> int:
    for d in plan.days:
        if any(i is v for i in d.items):
            return d.day
    raise AssertionError(f"{v.name} 不在任何一天")


# ------------------------------------------------------- ① 出圈出返程日


def test_far_card_evicted_from_single_city_last_day():
    """单城无腿末日=返程日镜像：出圈远卡挪去有容量的非端点日。"""
    a = _v("馆A", 60, _C0, 1, tier=9)
    b = _v("馆B", 60, _D2A, 2, tier=9)
    c = _v("馆C", 60, _D2B, 2, tier=9)
    far = _v("远郊园", 90, _FAR, 3, tier=5)
    near = _v("馆D", 60, _C1, 3, tier=9)
    plan = _plan(_d(1, a), _d(2, b, c), _d(3, far, near))
    _endpoint_day_light_sweep(plan, frozenset())
    assert _day_of(plan, far) == 2
    assert _day_of(plan, near) == 3
    # 11-13 起 90min 非街卡吃重磅翼（「不能安排大景点时间」拍板）：
    # 披露语素为「大景点」；远翼（距锚 >8km）同闸，两翼任一在案即可。
    assert any(
        "远郊园" in x and ("为大景点" in x or "距酒店或市中心较远" in x)
        for x in plan.assumptions
    )


def test_far_card_kept_and_disclosed_when_no_host():
    """无宿主=保留+披露（软放兜底同 11-08「排得上优先于排得轻」）。"""
    a = _v("馆A", 60, _C0, 1, tier=9)
    full = [_v(f"满员{k}", 100, _D2A, 2, tier=9) for k in range(4)]
    far = _v("远郊园", 90, _FAR, 3, tier=5)
    plan = _plan(_d(1, a), _d(2, *full), _d(3, far))
    _endpoint_day_light_sweep(plan, frozenset())
    assert _day_of(plan, far) == 3
    assert any("远郊园" in x and "暂保留" in x for x in plan.assumptions)


def test_pinned_far_card_untouched_on_return_day():
    """钉住=用户权威（铁律 19），出圈也不动。"""
    a = _v("馆A", 60, _C0, 1, tier=9)
    b = _v("馆B", 60, _D2A, 2, tier=9)
    far = _v("远郊园", 90, _FAR, 3, tier=5, pinned=True)
    plan = _plan(_d(1, a), _d(2, b), _d(3, far))
    _endpoint_day_light_sweep(plan, frozenset())
    assert _day_of(plan, far) == 3
    assert far.pinned is True


def test_departure_leg_day_far_card_evicted():
    """带定时离城腿的天=返程日（多城腿口径）：出圈远卡同样出。"""
    a = _v("馆A", 60, _C0, 1, tier=9)
    b = _v("馆B", 60, _D2A, 2, tier=9)
    c = _v("馆C", 60, _D2B, 2, tier=9)
    leg = TransferItem(
        item_id="t-xian-bj",
        day=3,
        seq=1,
        from_city="西安",
        to_city="北京",
        mode="train",
        start_time=time(14, 0),
        end_time=time(18, 0),
    )
    far = _v("远郊园", 90, _FAR, 3, tier=5)
    plan = _plan(_d(1, a), _d(2, b, c), _d(3, leg, far), cities=("西安", "北京"))
    _endpoint_day_light_sweep(plan, frozenset())
    assert _day_of(plan, far) == 2
    # 离城腿原位不动
    d3 = next(d for d in plan.days if d.day == 3)
    assert any(isinstance(i, TransferItem) for i in d3.items)


def test_in_circle_big_card_moves_out_of_return_day():
    """11-13 拍板「不能安排大景点时间」：>80min 非街卡即重磅——即便在
    8km 圈内也出返程日（旧 11-05 收轻口径被本拍板取代，test_return_
    day_accepts_big 为上游保位闸语义不动，终装清扫只管终装对账）。"""
    a = _v("馆A", 60, _C0, 1, tier=9)
    b = _v("馆B", 60, _D2A, 2, tier=9)
    big = _v("大馆", 120, _C1, 3, tier=5)
    plan = _plan(_d(1, a), _d(2, b), _d(3, big))
    _endpoint_day_light_sweep(plan, frozenset())
    assert _day_of(plan, big) == 2
    assert any("大馆" in x and "为大景点" in x for x in plan.assumptions)


def test_no_coords_card_not_evicted_uncheckable_stays():
    """「不可核即不拦」锚：无坐标卡在离城日=核不了出圈=绝不挪（11-08
    同口径；降级路无坐标卡被当出圈逐出城窗实录）。"""
    a = _v("馆A", 60, _C0, 1, tier=9)
    b = _v("馆B", 60, _D2A, 2, tier=9)
    blind = _v("无坐标馆", 60, None, 3, tier=5)
    plan = _plan(_d(1, a), _d(2, b), _d(3, blind))
    _endpoint_day_light_sweep(plan, frozenset())
    assert _day_of(plan, blind) == 3


def test_hotel_anchor_far_card_evicted_and_semantics():
    """11-13 双锚 AND 语义锚（用户根案：距城心 6km 但距酒店 11km 被判
    「远郊区」）：卡距城心锚在 8km 内、但距日酒店锚 >8km=违例出。轻
    时长（60min ≤80）+ 城心近 =只中酒店翼——证明两锚各自独立核。"""
    h = _v("酒店", 0, _HOTEL_FAR, 3, category="hotel")
    a = _v("馆A", 60, _C0, 1, tier=9)
    b = _v("馆B", 60, _D2A, 2, tier=9)
    near_center = _v("心边馆", 60, _C1, 3, tier=9)  # 距城心 ~0.1km
    plan = _plan(_d(1, a), _d(2, b), _d(3, h, near_center))
    _endpoint_day_light_sweep(plan, frozenset())
    assert _day_of(plan, near_center) == 2
    assert any("心边馆" in x and "距酒店或市中心较远" in x for x in plan.assumptions)


def test_tea_counts_as_legal_endpoint_content():
    """11-13 拍板「喝茶看秀」：tea_experience 卡=合法端点日内容——
    到达日只有茶卡时不吃空日留白披露，也不被①挪走。"""
    a = _v("馆A", 60, _C0, 1, tier=9)
    b = _v("馆B", 60, _D2A, 2, tier=9)
    tea = _v("茶馆", 60, _ST, 3, category="tea_experience")
    plan = _plan(_d(1, a), _d(2, b), _d(3, tea))
    _endpoint_day_light_sweep(plan, frozenset())
    assert _day_of(plan, tea) == 3
    assert not any("离城日" in x and "留白" in x for x in plan.assumptions)
    assert not any(
        "茶馆" in x and ("大景点" in x or "距酒店或市中心较远" in x)
        for x in plan.assumptions
    )


# ------------------------------------------------------- ② 空日留白披露


def test_empty_return_day_accepted_no_recruit():
    """11-11 拍板锚：离城日没收到简单街区卡=留白披露，**绝不从别日
    挪卡补**——哪怕源日有现成街卡。轻卡落位靠排程顺序自然发生。"""
    a = _v("馆A", 60, _C0, 1, tier=9)
    b = _v("馆B", 60, _D2A, 2, tier=9)
    st = _v("样本坊", 90, _ST, 2, tier=4)
    muse = _v("馆D", 60, _C1, 3, tier=9)
    plan = _plan(_d(1, a), _d(2, b, st), _d(3, muse))
    _endpoint_day_light_sweep(plan, frozenset())
    # 街卡原地不动（不跨日挪补）
    assert _day_of(plan, st) == 2
    assert _day_of(plan, muse) == 3
    assert any("离城日" in x and "留白" in x for x in plan.assumptions)


def test_return_day_with_simple_card_no_empty_disclosure():
    """返程日已有简单街区卡=空日披露不触发（有卡不留白）。"""
    a = _v("馆A", 60, _C0, 1, tier=9)
    b = _v("馆B", 60, _D2A, 2, tier=9)
    st = _v("样本坊", 90, _ST, 3, tier=4)
    plan = _plan(_d(1, a), _d(2, b), _d(3, st))
    _endpoint_day_light_sweep(plan, frozenset())
    assert _day_of(plan, st) == 3
    assert not any("离城日" in x and "留白" in x for x in plan.assumptions)


# ------------------------------------------------------- ③ 一项上限（11-12）


def test_return_day_two_cards_keeps_hotel_nearest():
    """11-12 拍板锚·离城日侧（用户根案「出发日安排了两项」）：两张圈内
    卡只留离酒店最近一张，另一张挪非端点日；披露在案。"""
    h = _v("酒店", 0, _C1, 3, category="hotel")
    a = _v("馆A", 60, _C0, 1, tier=9)
    b = _v("馆B", 60, _D2A, 2, tier=9)
    near = _v("近馆", 60, _ST, 3, tier=9)  # 距酒店 ~0.55km
    far2 = _v("边馆", 60, _MID, 3, tier=9)  # 圈内（①不挪）但离酒店更远
    plan = _plan(_d(1, a), _d(2, b), _d(3, h, near, far2))
    _endpoint_day_light_sweep(plan, frozenset())
    assert _day_of(plan, near) == 3
    assert _day_of(plan, far2) == 2
    assert any("只安排一项" in x and "边馆" in x for x in plan.assumptions)


def test_return_day_two_cards_defaults_to_city_center_without_hotel():
    """无酒店地址→市中心（城心锚）为默认：留距城心近者，余卡挪走。"""
    a = _v("馆A", 60, _C0, 1, tier=9)
    b = _v("馆B", 60, _D2A, 2, tier=9)
    c = _v("馆C", 60, _D2B, 2, tier=9)
    near = _v("心馆", 60, _C1, 3, tier=9)
    far2 = _v("边馆", 60, _EDGE, 3, tier=9)  # 圈内但明显更靠边缘
    plan = _plan(_d(1, a), _d(2, b, c), _d(3, near, far2))
    _endpoint_day_light_sweep(plan, frozenset())
    assert _day_of(plan, near) == 3
    assert _day_of(plan, far2) == 2
    assert any("只安排一项" in x and "边馆" in x for x in plan.assumptions)


def test_return_day_cap_keeps_pinned_extra():
    """余卡钉住=铁律 19：上限闸不挪钉卡（当日仍两张=用户权威）。"""
    h = _v("酒店", 0, _C1, 3, category="hotel")
    a = _v("馆A", 60, _C0, 1, tier=9)
    b = _v("馆B", 60, _D2A, 2, tier=9)
    near = _v("近馆", 60, _ST, 3, tier=9)
    far2 = _v("边馆", 60, _EDGE, 3, tier=9, pinned=True)
    plan = _plan(_d(1, a), _d(2, b), _d(3, h, near, far2))
    _endpoint_day_light_sweep(plan, frozenset())
    assert _day_of(plan, near) == 3
    assert _day_of(plan, far2) == 3
    assert far2.pinned is True
    assert not any("只安排一项" in x for x in plan.assumptions)


def test_return_day_cap_keeps_no_host_card_and_discloses():
    """无宿主=保留+披露（软放兜底「排得上优先于排得轻」，同①口径）。"""
    h = _v("酒店", 0, _C1, 3, category="hotel")
    a = _v("馆A", 60, _C0, 1, tier=9)
    full = [_v(f"满员{k}", 100, _D2A, 2, tier=9) for k in range(4)]
    near = _v("近馆", 60, _ST, 3, tier=9)
    far2 = _v("边馆", 60, _EDGE, 3, tier=9)
    plan = _plan(_d(1, a), _d(2, *full), _d(3, h, near, far2))
    _endpoint_day_light_sweep(plan, frozenset())
    assert _day_of(plan, near) == 3
    assert _day_of(plan, far2) == 3
    assert any(
        "只安排一项" in x and "边馆" in x and "暂保留" in x for x in plan.assumptions
    )


def test_return_day_cap_uncheckable_skips():
    """不可核即不拦：全无坐标且无酒店→上限核不了→两张都保留、无披露。"""
    a = _v("馆A", 60, None, 1, tier=9)
    b = _v("馆B", 60, None, 2, tier=9)
    blind1 = _v("无坐标甲", 60, None, 3, tier=9)
    blind2 = _v("无坐标乙", 60, None, 3, tier=9)
    plan = _plan(_d(1, a), _d(2, b), _d(3, blind1, blind2))
    _endpoint_day_light_sweep(plan, frozenset())
    assert _day_of(plan, blind1) == 3
    assert _day_of(plan, blind2) == 3
    assert not any("只安排一项" in x for x in plan.assumptions)
