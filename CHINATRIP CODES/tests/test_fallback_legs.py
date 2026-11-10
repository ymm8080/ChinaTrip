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


def test_fallback_chains_travel_between_sequenced_sights():
    """2026-11-03 用户 Day4 事故形态（旧版兜底产物 13:00→13:00 /
    14:30→14:30 背靠背，兵马俑零车程开场）：全未排点顺序链排时，
    相邻已排两点的间隔必须 ≥ 打车腿（无坐标对 ≥30）——兜底不得再
    产出零车程背靠背时刻；装不下 16:30 闸的点留空披露而非硬排。"""
    sights = [
        VisitItem(
            item_id="v16",
            name="陕西自然博物馆",
            city="西安",
            day=4,
            category="sight",
            # 75 分钟轻点：11-04 大点闸 15:30 下，全大点日链排不下第三点；
            # 本测验证的是腿链机制，轻点链让 4 点全落位。
            duration_minutes=75,
            location=GeoPoint(lon=108.9542, lat=34.2226),
        ),
        VisitItem(
            item_id="v15",
            name="小雁塔",
            city="西安",
            day=4,
            category="sight",
            duration_minutes=75,
            location=GeoPoint(lon=108.9437, lat=34.2419),
        ),
        VisitItem(
            item_id="v14",
            name="华清宫",
            city="西安",
            day=4,
            category="sight",
            duration_minutes=90,
            location=GeoPoint(lon=109.2119, lat=34.3621),
        ),
        VisitItem(
            item_id="v13",
            name="秦始皇兵马俑博物馆",
            city="西安",
            day=4,
            category="sight",
            duration_minutes=90,
            location=BMY_LOC,
        ),
    ]
    day = DayPlan(day=4, base_city="西安", items=list(sights))
    plan = ItineraryPlan(
        itinerary_id="it-d4", cities=["西安"], days=[day], assumptions=[]
    )
    _fallback_sequence_times(plan)
    placed = [s for s in sights if s.start_time is not None]
    # 11-05 结束闸：4 点 330min+腿 在 09:00-16:30 装不下 3 件以上
    # （兵马俑/华清宫 90min 场地板 15:00，午窗后第三点必越闸）——
    # 临潼两点成链即可验证腿链不变式，装不下的留空披露（docstring
    # 口径「留空披露而非硬排」）。
    assert len(placed) >= 2, "临潼两点（华清宫+兵马俑）应可落位"
    # 11-04 大点先排：兜底排序后时刻序≠列表序，腿链断言按时间序走
    # （不变式是「相邻时刻不背靠背零车程」，不是列表序）。
    placed.sort(key=lambda s: (s.start_time.hour, s.start_time.minute))
    for a, b in zip(placed, placed[1:]):
        gap = (b.start_time.hour * 60 + b.start_time.minute) - (
            a.end_time.hour * 60 + a.end_time.minute
        )
        leg = _taxi_leg_min(haversine_km(a.location, b.location))
        assert gap >= max(30, leg), (
            f"{a.name}→{b.name} 间隔 {gap} 分钟 < 打车腿 {leg}——背靠背零车程回归"
        )


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


def test_fallback_session_show_yields_far_blocker_keeps_cluster():
    """贴排对让位（2026-11-08 秦俑情 D2 甩空日案）：多场次演出全场次
    撞窗且当天有 ≤5km 贴排圈伴时，最晚可行场次撞到的远距（圈外）非
    钉住观光锚让位重排（untime 交后续 pass/挪日链），演出贴簇留住——
    不再甩空日单飞。贴排圈伴与钉住点永不让位。"""
    qyq_loc = GeoPoint(lon=109.2856, lat=34.3856)
    lishan_loc = GeoPoint(lon=109.2120, lat=34.3660)
    bmy150 = VisitItem(
        item_id="bmy150",
        name="秦始皇帝陵博物院",
        city="西安",
        day=2,
        category="sight",
        duration_minutes=150,
        start_time=_t(9, 0),
        end_time=_t(11, 30),
        location=BMY_LOC,
    )
    lishan = VisitItem(
        item_id="lishan",
        name="临潼骊山风景名胜区",
        city="西安",
        day=2,
        category="sight",
        duration_minutes=180,
        start_time=_t(14, 3),
        end_time=_t(17, 3),
        location=lishan_loc,
    )
    show = VisitItem(
        item_id="qyq",
        name="《秦俑情》",
        city="西安",
        day=2,
        category="entertainment",
        best_visit_time="show",
        duration_minutes=80,
        opening_hours="多场（约11:00/14:00/17:00，以当日公告为准）",
        location=qyq_loc,
    )
    day = DayPlan(day=2, base_city="西安", items=[bmy150, lishan, show])
    plan = ItineraryPlan(
        itinerary_id="it-y", cities=["西安"], days=[day], assumptions=[]
    )
    _fallback_sequence_times(plan)
    assert show.start_time == _t(17, 0), "秦俑情应守住簇日 17:00 场"
    assert lishan.start_time is None, "骊山应让位（untime 交后续 pass/挪日链）"
    assert bmy150.start_time == _t(9, 0), "贴排圈伴不动"


# 碑林伞名组合对（景区挂牌行 × 博物馆本体，词素「碑林」+ ~0.6km）
BL_SCENIC_LOC = GeoPoint(lon=108.9539, lat=34.2555)
BL_MUSEUM_LOC = GeoPoint(lon=108.9480, lat=34.2530)


def _bl_scenic():
    return VisitItem(
        item_id="bl-scenic",
        name="西安城墙·碑林历史文化景区",
        city="西安",
        day=2,
        category="sight",
        duration_minutes=180,
        location=BL_SCENIC_LOC,
    )


def _bl_museum():
    return VisitItem(
        item_id="bl-museum",
        name="西安碑林博物馆",
        city="西安",
        day=2,
        category="museum",
        duration_minutes=120,
        location=BL_MUSEUM_LOC,
    )


def _bl_banquet():
    return VisitItem(
        item_id="banquet",
        name="长安十二时辰·唐乐舞伴宴",
        city="西安",
        day=2,
        category="food",
        duration_minutes=90,
        pinned=True,
        soft_pin=True,
        start_time=_t(12, 0),
        end_time=_t(13, 30),
        poi_id="curated:banquet-x",
        location=GeoPoint(lon=108.9610, lat=34.2520),
    )


def _bell():
    return VisitItem(
        item_id="bell",
        name="西安钟楼",
        city="西安",
        day=2,
        category="sight",
        duration_minutes=60,
        location=ZL_LOC,
    )


def _min(t) -> int:
    return t.hour * 60 + t.minute


def test_fallback_combo_pair_no_third_card_between():
    """2026-11-10 拍板「组合成员之间不得落入第三卡」（碑林组合中间插
    宴秀卡案类级收口）：伞名组合对成员贴排落位；flex 餐不得缩档楔进
    组合成员之间——窗满按丢餐留痕（2026-11-08「餐卡可推迟/修订窗满
    丢餐」拍板），组合完整性强于一餐。"""
    scenic, museum, banquet, bell = (
        _bl_scenic(),
        _bl_museum(),
        _bl_banquet(),
        _bell(),
    )
    # 餐卡列表序夹在组合成员之间——放置序必须把成员挪成紧邻
    day = DayPlan(day=2, base_city="西安", items=[museum, banquet, scenic, bell])
    plan = ItineraryPlan(
        itinerary_id="it-bl", cities=["西安"], days=[day], assumptions=[]
    )
    _fallback_sequence_times(plan)
    assert scenic.start_time is not None, "组合景区应落位"
    assert museum.start_time is not None, "组合博物馆应落位"
    ends = sorted([_min(scenic.end_time), _min(museum.end_time)])
    starts = sorted([_min(scenic.start_time), _min(museum.start_time)])
    assert starts[1] - ends[0] <= 30, (
        f"组合成员脱节 >30 分钟交通垫：景区 {scenic.start_time}-{scenic.end_time} "
        f"博物馆 {museum.start_time}-{museum.end_time}——第三方可楔入"
    )
    # 成员间区间（贴排后应为空）不得有任何第三卡
    interior = (ends[0], starts[1])
    for it in day.items:
        if not isinstance(it, VisitItem) or it in (scenic, museum):
            continue
        if it.start_time is None:
            continue
        wedged = interior[0] <= _min(it.start_time) and _min(it.end_time) <= interior[1]
        assert not wedged, f"{it.name} 落在组合成员之间"
    # 午窗被贴排组合吃满 → 宴秀按窗满丢餐移除（留痕在日志），不缩档硬楔
    assert banquet not in day.items, "宴秀应窗满丢餐移除，不得缩档楔进组合"
    assert bell.start_time is not None, "第三方观光点应落在组合之后"
    assert _min(bell.start_time) >= ends[1], "钟楼应排在组合尾后"


def test_fallback_show_session_glued_to_tight_anchor():
    """2026-11-10 拍板「贴场馆演出与紧簇锚是一个排程单元」（贴锚演出被
    远距点隔开案类级收口）：多场次演出与同日 ≤1.5km 观光锚同单元——
    放置序挪到锚后紧邻、场次按与锚窗间隙升序（紧贴锚尾者优先），
    远距点不得楔入锚-演之间；不再全场次撞窗才想起贴排。"""
    anchor = VisitItem(
        item_id="anchor",
        name="近锚大点",
        city="西安",
        day=3,
        category="attraction",
        duration_minutes=90,
        location=BMY_LOC,
    )
    far = VisitItem(
        item_id="far",
        name="远距点",
        city="西安",
        day=3,
        category="attraction",
        duration_minutes=90,
        location=GeoPoint(lon=109.215, lat=34.359),
    )
    show = VisitItem(
        item_id="show",
        name="贴锚演出",
        city="西安",
        day=3,
        category="entertainment",
        best_visit_time="show",
        duration_minutes=80,
        opening_hours="多场（约11:00/14:00/17:00，以当日公告为准）",
        location=GeoPoint(lon=109.2809, lat=34.3804),
    )
    day = DayPlan(day=3, base_city="西安", items=[anchor, far, show])
    plan = ItineraryPlan(
        itinerary_id="it-show-glue", cities=["西安"], days=[day], assumptions=[]
    )
    _fallback_sequence_times(plan)
    assert anchor.start_time is not None and show.start_time is not None
    anchor_end = _min(anchor.end_time)
    show_start = _min(show.start_time)
    assert show_start == 11 * 60, (
        f"贴锚演出应取紧贴锚尾的 11:00 场，实际 {show.start_time}——"
        "晚场优先把锚演拆开了"
    )
    assert far.start_time is not None and _min(far.start_time) >= _min(
        show.end_time
    ), f"远距点 {far.start_time} 楔在锚-演之间"
    for it in day.items:
        if not isinstance(it, VisitItem) or it in (anchor, show):
            continue
        if it.start_time is None:
            continue
        assert not (
            anchor_end <= _min(it.start_time) and _min(it.end_time) <= show_start
        ), f"{it.name} 落在锚-演之间"


def test_fallback_show_without_tight_anchor_keeps_late_session():
    """防御纵深：无 ≤1.5km 紧簇锚时维持 2026-11-03「演出优先傍晚/晚场」
    拍板原序——贴锚新闸不得外溢成全局早场倾向。"""
    far = VisitItem(
        item_id="far",
        name="远距点",
        city="西安",
        day=3,
        category="attraction",
        duration_minutes=90,
        location=GeoPoint(lon=109.215, lat=34.359),
    )
    show = VisitItem(
        item_id="show",
        name="孤立演出",
        city="西安",
        day=3,
        category="entertainment",
        best_visit_time="show",
        duration_minutes=80,
        opening_hours="多场（约11:00/14:00/17:00，以当日公告为准）",
        location=BMY_LOC,
    )
    day = DayPlan(day=3, base_city="西安", items=[far, show])
    plan = ItineraryPlan(
        itinerary_id="it-show-late", cities=["西安"], days=[day], assumptions=[]
    )
    _fallback_sequence_times(plan)
    assert show.start_time is not None
    assert _min(show.start_time) == 17 * 60, (
        f"无紧簇锚应维持晚场优先（17:00），实际 {show.start_time}"
    )


def test_fallback_combo_pair_kept_when_user_order_authoritative():
    """keep_list_order（2026-10-24「用户顺序权威」拍板）：用户权威路径
    不启用组合防插/贴排——用户亲手把第三方排在组合中间时引擎不顶回。"""
    scenic, bell, museum = _bl_scenic(), _bell(), _bl_museum()
    day = DayPlan(day=2, base_city="西安", items=[scenic, bell, museum])
    plan = ItineraryPlan(
        itinerary_id="it-bl2", cities=["西安"], days=[day], assumptions=[]
    )
    _fallback_sequence_times(plan, keep_list_order=True)
    assert bell.start_time is not None and museum.start_time is not None
    assert _min(bell.start_time) < _min(museum.start_time), (
        "keep_list_order 下不得重排用户列表序（第三方留在组合中间）"
    )
