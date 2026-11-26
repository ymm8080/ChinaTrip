# -*- coding: utf-8 -*-
"""空档补点（收尾第③步）2026-11-16 上海案：下限/餐窗/重日短件/上限/幂等。"""

from __future__ import annotations

import asyncio
from datetime import time

from app.services.agent.plan import (
    PlanningAgent,
    PlanSession,
    _fill_leftover_with_diverse_sights,
)
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    UnplacedCandidate,
    VisitItem,
)


def _v(item_id, name, start, end, *, cat="sight", lon=121.47, lat=31.23, **kw):
    dur = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
    return VisitItem(
        item_id=item_id,
        name=name,
        city="上海",
        day=1,
        category=cat,
        duration_minutes=kw.pop("dur", dur),
        location=GeoPoint(lon=lon, lat=lat),
        start_time=start,
        end_time=end,
        **kw,
    )


def _hm(start, end):
    """晨卡（从酒店出发）：识别只看 item_id 前缀。"""
    return _v("hotel-morning-d1", "出发", start, end, cat="hotel")


def _food(name, start, end, lon=121.49, lat=31.24):
    return _v(name, name, start, end, cat="food", lon=lon, lat=lat)


def _cand(name, dur, lon=121.52, lat=31.20, *, cat="sight", bvt=None, city="上海"):
    return UnplacedCandidate(
        name=name,
        category=cat,
        duration_minutes=dur,
        location=GeoPoint(lon=lon, lat=lat),
        city=city,
        poi_id=name,
        best_visit_time=bvt,
    )


def _plan(items, *, assumptions=None):
    return ItineraryPlan(
        itinerary_id="t",
        cities=["上海"],
        days=[DayPlan(day=1, base_city="上海", items=items)],
        assumptions=list(assumptions or []),
    )


def _placed(plan, name):
    return next(i for i in plan.days[0].items if i.name == name)


def test_fill_starts_after_hotel_morning_card():
    """晨卡 10:30-11:00：补点不得排到出发卡之前（旧口径 08:30 就出门）。"""
    plan = _plan(
        [_hm(time(10, 30), time(11, 0)), _food("晚饭", time(19, 0), time(20, 30))]
    )
    notes = _fill_leftover_with_diverse_sights(plan, bench=[_cand("测试景点", 90)])
    assert notes
    assert _placed(plan, "测试景点").start_time >= time(11, 0)


def test_fill_does_not_overlap_real_lunch_card():
    """真实午饭 11:45-12:45 是墙：补点只能从餐后开始。"""
    plan = _plan(
        [
            _hm(time(11, 0), time(11, 30)),
            _food("午饭", time(11, 45), time(12, 45)),
            _food("晚饭", time(19, 0), time(20, 30)),
        ]
    )
    notes = _fill_leftover_with_diverse_sights(plan, bench=[_cand("测试景点", 60)])
    assert notes
    placed = _placed(plan, "测试景点")
    assert placed.start_time >= time(12, 45)
    assert placed.start_time != time(11, 45)


def test_heavy_day_still_takes_a_short_sight():
    """重日（必去 180+120=300）仍有空档时，≤90 分钟的短件要补得进来。"""
    plan = _plan(
        [
            _v(
                "m",
                "博物馆",
                time(9, 0),
                time(12, 0),
                cat="museum",
                must=True,
                dur=180,
            ),
            _food("午饭", time(12, 0), time(13, 0)),
            _v(
                "bund",
                "外滩",
                time(17, 0),
                time(19, 0),
                cat="nature",
                must=True,
                dur=120,
            ),
            _food("晚饭", time(19, 0), time(20, 30)),
        ]
    )
    notes = _fill_leftover_with_diverse_sights(
        plan, bench=[_cand("短景点", 60, 121.50, 31.22)]
    )
    assert notes
    assert _placed(plan, "短景点").start_time == time(13, 0)


def test_fill_skips_day_with_four_sights():
    """一天已 4 张观光卡：补点不再加第 5 张（与选点期同口径）。"""
    plan = _plan(
        [
            _v("a", "景点A", time(9, 0), time(10, 0), lon=121.40, lat=31.20),
            _v("b", "景点B", time(10, 30), time(11, 30), lon=121.44, lat=31.24),
            _v("c", "景点C", time(14, 0), time(15, 0), lon=121.50, lat=31.28),
            _v("d", "景点D", time(15, 30), time(16, 30), lon=121.54, lat=31.20),
            _food("午饭", time(12, 0), time(13, 0)),
            _food("晚饭", time(19, 0), time(20, 30)),
        ]
    )
    assert _fill_leftover_with_diverse_sights(plan, bench=[_cand("第五个", 90)]) == []


def test_fill_skips_micro_gaps_and_micro_sights():
    """45 分钟空档 + 30 分钟件：都不补（边角料只是凑数）。"""
    plan = _plan(
        [
            _hm(time(10, 30), time(11, 0)),
            _food("午饭", time(11, 45), time(12, 45)),
            _food("晚饭", time(19, 0), time(20, 30)),
        ]
    )
    assert _fill_leftover_with_diverse_sights(plan, bench=[_cand("观景厅", 30)]) == []


def test_fill_is_idempotent_via_disclosure_marker():
    """披露即标记：同一份行程第二次补点必须空转（开页刷新不叠加）。"""
    plan = _plan(
        [_hm(time(10, 30), time(11, 0)), _food("晚饭", time(19, 0), time(20, 30))]
    )
    first = _fill_leftover_with_diverse_sights(plan, bench=[_cand("测试景点", 90)])
    assert first
    assert _fill_leftover_with_diverse_sights(plan, bench=[_cand("另一个点", 90)]) == []


def test_evening_candidate_never_before_five_pm():
    """best_visit_time=evening 的件不得排到 17:00 之前（浦江游览 12:45 案）。"""
    plan = _plan(
        [
            _hm(time(8, 30), time(9, 0)),
            _food("午饭", time(12, 0), time(13, 0)),
            _food("晚饭", time(19, 0), time(20, 30)),
        ]
    )
    notes = _fill_leftover_with_diverse_sights(
        plan, bench=[_cand("浦江夜游", 120, bvt="evening")]
    )
    assert notes
    placed = _placed(plan, "浦江夜游")
    assert placed.start_time >= time(17, 0)
    assert placed.end_time <= time(19, 0)


def test_fill_refills_morning_when_card_moved_back_to_day_start():
    """晨卡回拨日始后上午空出来：已有「补过」标记也要再补一次（上海 D1）。"""
    card = _hm(time(8, 30), time(9, 0))
    plan = _plan(
        [
            card,
            _food("午饭", time(11, 45), time(12, 45)),
            _food("晚饭", time(19, 0), time(20, 30)),
        ],
        assumptions=["第1天还有空档，按类型多样性补了「黄浦江游览」（12:45）"],
    )
    notes = _fill_leftover_with_diverse_sights(plan, bench=[_cand("豫园", 90)])
    assert notes
    placed = _placed(plan, "豫园")
    assert placed.start_time == time(9, 0)
    assert placed.end_time == time(10, 30)
    # 补完上午不再有 opening hole → 第二次必须空转（不越补越多）
    assert _fill_leftover_with_diverse_sights(plan, bench=[_cand("另一个点", 90)]) == []


def test_fill_keeps_skipping_filled_day_without_opening_hole():
    """已补过 + 首件就在日始：仍是零改动（旧幂等口径不回退）。"""
    plan = _plan(
        [
            _hm(time(8, 30), time(9, 0)),
            _v("a", "景点A", time(9, 0), time(10, 30), lon=121.44, lat=31.24),
            _food("午饭", time(11, 45), time(12, 45)),
            _food("晚饭", time(19, 0), time(20, 30)),
        ],
        assumptions=["第1天还有空档，按类型多样性补了「景点A」（09:00）"],
    )
    assert _fill_leftover_with_diverse_sights(plan, bench=[_cand("豫园", 90)]) == []


def test_fill_uses_afternoon_after_incity_return_leg():
    """同城回城腿（access-*）不套 90 分钟跨城缓冲：15:01 落地后下午要能用。

    2026-11-16 用户「day1 回城以后才三四点，为什么不安排其它节目？」：
    朱家角回城卡 14:00-15:01 被旧口径铺成 12:30-16:31，普通件进场闸
    15:30 之后整段下午判死，补点永远补不进来。
    """
    from app.services.agent.plan import _day_fixed_windows
    from app.services.itinerary.models import TransferItem

    ret = TransferItem(
        item_id="access-return-extras-2-朱家角大清邮局",
        day=2,
        seq=0,
        from_city="",
        to_city="",
        mode="car",
        start_time=time(14, 0),
        end_time=time(15, 1),
        duration_minutes=61,
    )
    day = DayPlan(
        day=2,
        base_city="上海",
        items=[
            _hm(time(8, 30), time(9, 0)),
            _v(
                "zjj",
                "朱家角古镇",
                time(9, 0),
                time(12, 0),
                cat="attraction",
                lon=121.05,
                lat=31.11,
            ),
            _food("午饭", time(12, 0), time(13, 0)),
            _v(
                "post",
                "大清邮局",
                time(13, 10),
                time(14, 10),
                cat="other",
                lon=121.05,
                lat=31.11,
            ),
            ret,
            _food("晚饭", time(19, 10), time(20, 40)),
        ],
    )
    fixed, _tight, _flex, _xfer = _day_fixed_windows(day)
    win = next(w for w in fixed if w[2] is None)
    # 只有 15 分钟换乘余量，不是 ±90 跨城缓冲
    assert win[:2] == (14 * 60 - 15, 15 * 60 + 1 + 15)
    plan = ItineraryPlan(itinerary_id="t", cities=["上海"], days=[day], assumptions=[])
    notes = _fill_leftover_with_diverse_sights(
        plan, bench=[_cand("田子坊", 90, 121.47, 31.21)]
    )
    assert notes
    placed = next(i for i in day.items if getattr(i, "name", "") == "田子坊")
    assert placed.start_time >= time(15, 1)
    assert placed.end_time <= time(19, 0)


def test_intercity_transfer_keeps_ninety_minute_buffer():
    """真跨城腿仍是铁律 4 的 90 分钟衔接缓冲（别把同城口径扩大化）。"""
    from app.services.agent.plan import _day_fixed_windows
    from app.services.itinerary.models import TransferItem

    leg = TransferItem(
        item_id="x1",
        day=1,
        seq=0,
        from_city="上海",
        to_city="北京",
        mode="train",
        start_time=time(14, 0),
        end_time=time(18, 0),
        duration_minutes=240,
    )
    day = DayPlan(day=1, base_city="上海", items=[leg])
    from app.services.itinerary.models import arrival_floor_minutes

    fixed, _tight, _flex, _xfer = _day_fixed_windows(day)
    win = next(w for w in fixed if w[2] is None)
    assert win[:2] == (14 * 60 - 90, 18 * 60 + arrival_floor_minutes("train"))


class _FakeDetails:
    def top_pois_in_city(self, city, limit=30, **kw):
        return [
            {
                "poi_id": "bench-1",
                "name": "库内景点",
                "category": "sight",
                "tier": 2,
                "suggested_duration_min": 90,
                "location": (121.52, 31.20),
                "tags": [],
            }
        ]


def test_fill_leftover_gaps_appends_notes_and_is_session_idempotent():
    plan = _plan(
        [_hm(time(10, 30), time(11, 0)), _food("晚饭", time(19, 0), time(20, 30))]
    )
    agent = PlanningAgent.__new__(PlanningAgent)
    agent._poi_details = _FakeDetails()
    session = PlanSession(
        session_id="s1", device_id="d1", cities=["上海"], days=1, plan=plan
    )
    notes = asyncio.run(agent.fill_leftover_gaps(session))
    assert notes
    assert all(n in session.plan.assumptions for n in notes)
    assert asyncio.run(agent.fill_leftover_gaps(session)) == []


def test_bench_candidates_carry_tier_and_rating():
    """bench 候选必须带上库行的档位/评分（2026-11-17）：真实库此前把
    _tier 出库前剥掉、rating 根本不在候选上——补点排序两个质量键全失效。"""
    from app.services.agent.plan import _bench_candidates_from_library

    rows = [
        {
            "poi_id": "ct_sh_240",
            "name": "北外滩国客中心沙滩嘉年华",
            "category": "theme_park",
            "tier": 3,
            "rating": None,
            "suggested_duration_min": 240,
            "location": (121.5156, 31.2521),
            "tags": ["intl", "layla"],
        },
        {
            "poi_id": "ct_sh_71",
            "name": "新天地",
            "category": "attraction",
            "tier": 1,
            "rating": 4.5,
            "suggested_duration_min": 90,
            "location": (121.4748, 31.2199),
            "tags": ["lp", "intl"],
        },
    ]
    by = {c.name: c for c in _bench_candidates_from_library(rows, city="上海")}
    assert by["新天地"].tier == 1 and by["新天地"].rating == 4.5
    assert by["北外滩国客中心沙滩嘉年华"].rating is None


def test_fill_zero_evidence_intl_tag_loses_to_rated_candidate():
    """沙滩嘉年华案回归（2026-11-17 用户「补点也要看 priority 与 rating」）：
    intl 牌+零评分的 bulk 行不得靠快车道压过有口碑的候选——两候选档位
    同空、同在 bench，rating 降序让有评分的先补（旧行为嘉年华第一）。"""
    carnival = UnplacedCandidate(
        name="沙滩嘉年华",
        category="theme_park",
        duration_minutes=240,
        location=GeoPoint(lon=121.52, lat=31.20),
        city="上海",
        poi_id="c1",
        tags=["intl", "layla"],
        rating=None,
        reason="library_bench",
    )
    rated = UnplacedCandidate(
        name="有口碑景点",
        category="attraction",
        duration_minutes=90,
        location=GeoPoint(lon=121.48, lat=31.21),
        city="上海",
        poi_id="c2",
        tags=[],
        rating=4.5,
        reason="library_bench",
    )
    plan = _plan(
        [_hm(time(8, 30), time(9, 0)), _food("晚饭", time(19, 0), time(20, 30))]
    )
    notes = _fill_leftover_with_diverse_sights(plan, bench=[carnival, rated])
    assert notes
    assert "有口碑景点" in notes[0]
    assert _placed(plan, "有口碑景点").start_time == time(9, 0)


def test_rated_intl_candidate_keeps_express_lane():
    """11-15 拍板保留：有口碑的 INTL 候选仍压过同条件的普通候选。"""
    intl = UnplacedCandidate(
        name="国际荐点景点",
        category="attraction",
        duration_minutes=90,
        location=GeoPoint(lon=121.50, lat=31.22),
        city="上海",
        poi_id="c3",
        tags=["intl"],
        rating=4.6,
        reason="library_bench",
    )
    plain = UnplacedCandidate(
        name="普通景点",
        category="park",
        duration_minutes=90,
        location=GeoPoint(lon=121.46, lat=31.20),
        city="上海",
        poi_id="c4",
        tags=[],
        rating=4.8,
        reason="library_bench",
    )
    plan = _plan(
        [_hm(time(8, 30), time(9, 0)), _food("晚饭", time(19, 0), time(20, 30))]
    )
    notes = _fill_leftover_with_diverse_sights(plan, bench=[plain, intl])
    assert notes
    assert "国际荐点景点" in notes[0]


def test_return_day_fill_rejects_third_cluster_candidate():
    """回城日豁免收口（2026-11-17 慕田峪案）：既不贴当天簇、又出市区圈
    （城心 25km）的候选不得补进回城日——八达岭观景台之于慕田峪天，
    补进来就在午饭卡上挂出 199 分钟「班车+打车 ¥145」怪腿。"""
    from app.services.itinerary.models import TransferItem

    ret = TransferItem(
        item_id="access-return-v-mty",
        day=1,
        seq=0,
        from_city="",
        to_city="",
        mode="car",
        start_time=time(12, 10),
        end_time=time(13, 0),
        duration_minutes=50,
    )
    plan = _plan(
        [
            _hm(time(8, 30), time(9, 0)),
            _v(
                "mty",
                "远郊景区",
                time(9, 0),
                time(12, 0),
                cat="nature",
                must=True,
                dur=180,
                lon=121.05,
                lat=31.11,
            ),
            ret,
            _food("晚饭", time(19, 0), time(20, 30)),
        ]
    )
    far = _cand("第三个片区景点", 90, 121.90, 31.05)
    assert _fill_leftover_with_diverse_sights(plan, bench=[far]) == []
    assert not any(
        getattr(i, "name", "") == "第三个片区景点" for i in plan.days[0].items
    )


def test_return_day_fill_takes_city_circle_candidate():
    """回城日豁免放行市区圈（≤25km）候选：回城后的空档照旧补市区点。"""
    from app.services.itinerary.models import TransferItem

    ret = TransferItem(
        item_id="access-return-v-mty",
        day=1,
        seq=0,
        from_city="",
        to_city="",
        mode="car",
        start_time=time(12, 10),
        end_time=time(13, 0),
        duration_minutes=50,
    )
    plan = _plan(
        [
            _hm(time(8, 30), time(9, 0)),
            _v(
                "mty",
                "远郊景区",
                time(9, 0),
                time(12, 0),
                cat="nature",
                must=True,
                dur=180,
                lon=121.05,
                lat=31.11,
            ),
            ret,
            _food("晚饭", time(19, 0), time(20, 30)),
        ]
    )
    city = _cand("田子坊", 90, 121.49, 31.22)
    notes = _fill_leftover_with_diverse_sights(plan, bench=[city])
    assert notes
    assert any(getattr(i, "name", "") == "田子坊" for i in plan.days[0].items)


def test_day_already_remote_anchors_on_day_city_anchor():
    """远郊日判定改用当天市区锚（2026-11-17）：不再被全行程质心拖偏——
    慕田峪案里质心北移后八达岭观景台 60km 反而判「不远」。"""
    from app.services.agent.plan import _day_already_remote

    day1 = DayPlan(
        day=1,
        base_city="上海",
        items=[
            _v("a", "市区景点A", time(9, 0), time(10, 0), lon=121.47, lat=31.23),
            _v(
                "r",
                "远郊大景区",
                time(11, 0),
                time(14, 0),
                cat="nature",
                lon=121.47,
                lat=31.85,
            ),
        ],
    )
    day2 = DayPlan(
        day=2,
        base_city="上海",
        items=[_v("b", "市区景点B", time(9, 0), time(12, 0), lon=121.47, lat=31.23)],
    )
    plan = ItineraryPlan(
        itinerary_id="t", cities=["上海"], days=[day1, day2], assumptions=[]
    )
    # 旧口径：全行程质心 ≈ (121.47, 31.48)，远郊件距质心 ~40km < 50 → 漏判
    # 新口径：距当天市区锚（城心）~68km > 50 → 判远郊
    assert _day_already_remote(plan, day1) is True


def test_evict_third_cluster_extras_removes_far_and_keeps_cluster_near():
    """历史脏卡回扫：离簇又离市区圈的 extras- 补点件移出并披露；
    贴簇的（朱家角大清邮局案）原样保留；二次调用零改动。"""
    from app.services.agent.plan import _evict_third_cluster_extras

    far = _v(
        "extras-1-远点观景台",
        "远点观景台",
        time(14, 0),
        time(15, 0),
        cat="nature",
        lon=121.90,
        lat=31.05,
    )
    near = _v(
        "extras-1-近点小馆",
        "近点小馆",
        time(15, 10),
        time(16, 10),
        cat="other",
        lon=121.06,
        lat=31.11,
    )
    plan = _plan(
        [
            _hm(time(8, 30), time(9, 0)),
            _v("a", "簇内景点", time(9, 0), time(12, 0), lon=121.05, lat=31.11),
            _food("晚饭", time(19, 0), time(20, 30)),
            far,
            near,
        ]
    )
    notes = _evict_third_cluster_extras(plan)
    assert notes and "远点观景台" in notes[0]
    names = {i.name for i in plan.days[0].items}
    assert "远点观景台" not in names
    assert "近点小馆" in names
    assert _evict_third_cluster_extras(plan) == []


def test_fill_leftover_gaps_evicts_third_cluster_extras_on_old_sessions():
    """旧会话开档即治（已补短路之前跑）：脏 extras 卡不等人重新生成。"""
    far = _v(
        "extras-1-远点观景台",
        "远点观景台",
        time(14, 0),
        time(15, 0),
        cat="nature",
        lon=121.90,
        lat=31.05,
    )
    plan = _plan(
        [
            _hm(time(8, 30), time(9, 0)),
            _v("a", "簇内景点", time(9, 0), time(12, 0), lon=121.05, lat=31.11),
            _food("晚饭", time(19, 0), time(20, 30)),
            far,
        ],
        assumptions=["第1天还有空档，按类型多样性补了「远点观景台」（14:00）"],
    )
    agent = PlanningAgent.__new__(PlanningAgent)
    agent._poi_details = None
    session = PlanSession(
        session_id="s2", device_id="d2", cities=["上海"], days=1, plan=plan
    )
    notes = asyncio.run(agent.fill_leftover_gaps(session))
    assert notes and "远点观景台" in notes[0]
    assert all(i.name != "远点观景台" for i in session.plan.days[0].items)
    assert all(n in session.plan.assumptions for n in notes)


def test_fill_leftover_time_bench_includes_unplaced():
    # 2026-11-22 起始城停留案：Day2 上午 240min 空档，天安门/天坛/恭王府
    # 躺在 unplaced（cluster_day/day_overflow）——docstring 口径
    # 「池 = plan.unplaced + 同城库 top 200」，实现漏了前一半，空天宁可
    # 白着也不回填。探针排得进就排回，排不进留在想去。
    class _EmptyStore:
        def top_pois_in_city(self, city, n):
            return []

    plan = ItineraryPlan(
        itinerary_id="t",
        cities=["北京"],
        days=[
            DayPlan(
                day=2,
                base_city="北京",
                items=[
                    VisitItem(
                        item_id="hotel-morning-d2",
                        name="出发",
                        city="北京",
                        day=2,
                        category="hotel",
                        duration_minutes=30,
                        location=GeoPoint(lon=116.40, lat=39.90),
                        start_time=time(8, 30),
                        end_time=time(9, 0),
                    ),
                    VisitItem(
                        item_id="food-lunch-ph-d2",
                        name="午饭（自由安排）",
                        city="北京",
                        day=2,
                        category="food",
                        duration_minutes=60,
                        location=GeoPoint(lon=116.40, lat=39.90),
                        start_time=time(13, 0),
                        end_time=time(14, 0),
                    ),
                    VisitItem(
                        item_id="v10",
                        name="晚饭（自由安排）",
                        city="北京",
                        day=2,
                        category="food",
                        duration_minutes=90,
                        location=GeoPoint(lon=116.40, lat=39.90),
                        start_time=time(19, 0),
                        end_time=time(20, 30),
                    ),
                ],
            )
        ],
        unplaced=[
            UnplacedCandidate(
                name="天坛公园",
                category="sight",
                duration_minutes=120,
                location=GeoPoint(lon=116.41, lat=39.88),
                city="北京",
                poi_id="tiantan",
                reason="day_overflow",
            )
        ],
    )
    agent = PlanningAgent(object())  # llm 占位：本路径不触 llm
    agent._poi_details = _EmptyStore()
    notes = asyncio.run(agent._fill_leftover_time(plan))
    names = [i.name for i in plan.days[0].items]
    assert "天坛公园" in names
    assert any("天坛公园" in n for n in notes)
    placed = next(i for i in plan.days[0].items if i.name == "天坛公园")
    assert placed.start_time >= time(9, 0)
    assert placed.end_time <= time(13, 0)  # 午饭前


def test_bridge_rendering_card_never_blocks_afternoon_fill():
    # 2026-11-22 起始城停留案 Day2：leg-bridge-* 桥卡（渲染件，响应层
    # attach_gap_bridges 按最终形状重挂）14:00-19:00 在 _day_fixed_windows
    # 走 else 分支当 ±30 墙 → 下午整档判死，补进的天坛被顺延链推过午夜
    # 又被越午夜清闸撤下。桥卡不得当墙。
    plan = ItineraryPlan(
        itinerary_id="t",
        cities=["北京"],
        days=[
            DayPlan(
                day=2,
                base_city="北京",
                items=[
                    VisitItem(
                        item_id="hotel-morning-d2",
                        name="出发",
                        city="北京",
                        day=2,
                        category="hotel",
                        duration_minutes=30,
                        location=GeoPoint(lon=116.40, lat=39.90),
                        start_time=time(8, 30),
                        end_time=time(9, 0),
                    ),
                    VisitItem(
                        item_id="food-lunch-ph-d2",
                        name="午饭（自由安排）",
                        city="北京",
                        day=2,
                        category="food",
                        duration_minutes=60,
                        location=GeoPoint(lon=116.40, lat=39.90),
                        start_time=time(13, 0),
                        end_time=time(14, 0),
                    ),
                    VisitItem(
                        item_id="leg-bridge-d2-4",
                        name="🕒 自由活动，随后前往下一站·约30分钟",
                        city="北京",
                        day=2,
                        category="transfer",
                        duration_minutes=300,
                        location=None,
                        start_time=time(14, 0),
                        end_time=time(19, 0),
                    ),
                    VisitItem(
                        item_id="v10",
                        name="晚饭（自由安排）",
                        city="北京",
                        day=2,
                        category="food",
                        duration_minutes=90,
                        location=GeoPoint(lon=116.40, lat=39.90),
                        start_time=time(19, 0),
                        end_time=time(20, 30),
                    ),
                ],
            )
        ],
    )
    notes = _fill_leftover_with_diverse_sights(
        plan, bench=[_cand("天坛公园", 120, lon=116.41, lat=39.88, city="北京")]
    )
    placed = next(i for i in plan.days[0].items if i.name == "天坛公园")
    assert placed.start_time is not None
    s = placed.start_time.hour * 60 + placed.start_time.minute
    e = placed.end_time.hour * 60 + placed.end_time.minute
    assert 9 * 60 <= s and e <= 19 * 60  # 当天空档内落位（上午/下午均可），不越晚饭
    assert any("天坛公园" in n for n in notes)
