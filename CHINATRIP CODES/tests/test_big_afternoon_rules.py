# -*- coding: utf-8 -*-
"""大点三口径回归（2026-11-04 用户拍板「大型的旅游景区不适合放下午
16:00。超过80分钟的一般下午就放一个。然后搭配一个近距离的CITYWALK。
当天应该先排大明宫，再排西安钟楼」）：

- 入场闸加严（大点 15:30）在 test_entry_cap_gate.py；
- 求解器 CP/插入双路：大点先排（大明宫先、钟楼后）+ 下午单大点；
- 评分器同口径软罚（LNS 不把第二个大点挪进下午、不把大点排轻点后）
  与硬闸对齐（大点 15:30 后开场计硬违规）；
- 回填配对：已有大点的天优先补大点近旁街区（tier8 ≤6km），不顶格
  补第二个重磅。
"""

from datetime import time as _t

from app.services.agent.plan import PlanningAgent
from app.services.itinerary.models import DayPlan, ItineraryPlan, VisitItem
from app.services.itinerary.solver import solve_day


def _visit(item_id, name, *, dur, tier=None, **kw):
    base = dict(
        item_id=item_id,
        name=name,
        city="西安",
        day=1,
        duration_minutes=dur,
        tier=tier,
        category="sight",
    )
    base.update(kw)
    return VisitItem(**base)


def _minutes(v: VisitItem) -> int:
    assert v.start_time is not None
    return v.start_time.hour * 60 + v.start_time.minute


# --- 求解器 CP 路：大点先排 + 下午单大点 ---------------------------------


def test_solver_schedules_big_before_light():
    # 「先排大明宫，再排西安钟楼」：同日大点排在轻点之后计罚（软罚
    # 压过 makespan），无他档时零罚解=大点先行。
    dm = _visit("dm", "大明宫遗址公园", dur=240, tier=2)
    zt = _visit("zt", "西安钟楼", dur=40, tier=5)
    out = solve_day(DayPlan(day=1, base_city="西安", items=[zt, dm]), poi_hours=[])
    assert out is not None
    starts = {v.item_id: _minutes(v) for v in out.items if isinstance(v, VisitItem)}
    assert starts["dm"] < starts["zt"]


def test_solver_keeps_one_big_in_afternoon():
    # 「超过80分钟的一般下午就放一个」：城墙(120)+大雁塔(90) 双大点
    # 落位后，下午（≥13:00 开场）的大点 ≤1——第二个被罚进上午。
    cq = _visit("cq", "西安城墙", dur=120, tier=2)
    dyt = _visit("dyt", "大雁塔", dur=90, tier=2)
    hj = _visit("hj", "回民街", dur=120, tier=8)
    out = solve_day(DayPlan(day=1, base_city="西安", items=[cq, dyt, hj]), poi_hours=[])
    assert out is not None
    starts = {v.item_id: _minutes(v) for v in out.items if isinstance(v, VisitItem)}
    aft_bigs = sum(1 for i in ("cq", "dyt") if starts[i] >= 13 * 60)
    assert aft_bigs <= 1


def test_solver_end_cap_holds_in_solve():
    # 结束闸（11-05 终裁）在 solver 主路成立：240 分钟大点最晚 12:30
    # 开场（13:00 收尾后不再占用），不可能被排到 15:30 后开场（旧
    # 开场带）——普通 60 分钟点最晚 15:30 开场（16:00 起排即 17:00
    # 收尾越闸，对照锚）。
    dm = _visit("dm", "大明宫遗址公园", dur=240, tier=2)
    out = solve_day(DayPlan(day=1, base_city="西安", items=[dm]), poi_hours=[])
    assert out is not None
    starts = {v.item_id: _minutes(v) for v in out.items if isinstance(v, VisitItem)}
    assert starts["dm"] <= 12 * 60 + 30
    small = _visit("sm", "小点", dur=60, tier=9)
    out2 = solve_day(DayPlan(day=1, base_city="西安", items=[small]), poi_hours=[])
    assert out2 is not None
    starts2 = {v.item_id: _minutes(v) for v in out2.items if isinstance(v, VisitItem)}
    assert starts2["sm"] <= 15 * 60 + 30


# --- 评分器：同口径软罚 + 硬闸对齐 ---------------------------------------


def _plan(*days_items):
    return ItineraryPlan(
        itinerary_id="it-x",
        cities=["西安"],
        days=[
            DayPlan(day=i + 1, base_city="西安", items=list(items))
            for i, items in enumerate(days_items)
        ],
        assumptions=[],
    )


def test_scorer_flags_second_afternoon_big():
    from app.services.itinerary.scoring import PEN_AFTERNOON_CROWD, plan_score

    a = _visit(
        "a",
        "大雁塔",
        dur=90,
        tier=2,
        start_time=_t(14, 0),
        end_time=_t(15, 20),
    )
    b = _visit(
        "b",
        "西安城墙",
        dur=90,
        tier=2,
        start_time=_t(15, 20),
        end_time=_t(16, 50),
    )
    sc = plan_score(_plan([a, b]))
    assert sc.counts["afternoon_crowd"] == 1
    assert sc.soft["afternoon_crowd"] == -PEN_AFTERNOON_CROWD


def test_scorer_flags_big_after_light():
    from app.services.itinerary.scoring import PEN_LATE_BIG, plan_score

    zt = _visit(
        "zt",
        "西安钟楼",
        dur=40,
        tier=5,
        start_time=_t(10, 0),
        end_time=_t(10, 40),
    )
    dm = _visit(
        "dm",
        "大明宫遗址公园",
        dur=240,
        tier=2,
        start_time=_t(14, 0),
        end_time=_t(18, 0),
    )
    sc = plan_score(_plan([zt, dm]))
    assert sc.counts["late_big"] == 1
    assert sc.soft["late_big"] == -PEN_LATE_BIG


def test_scorer_big_occupying_after_1630_is_hard_violation():
    from app.services.itinerary.scoring import plan_score

    # 11-05 终裁=结束闸：16:00 开场的大点占用到 20:00，越闸计迟
    # （旧口径断言「16:00 开场>15:30 开场带」同形态，结束闸下语义不变）。
    dm = _visit(
        "dm",
        "大明宫遗址公园",
        dur=240,
        tier=2,
        start_time=_t(16, 0),
        end_time=_t(20, 0),
    )
    sc = plan_score(_plan([dm]))
    assert sc.counts["late_entries"] == 1
    assert not sc.ok


def test_scorer_street_and_small_sights_not_big():
    from app.services.itinerary.scoring import plan_score

    # 街区 tier8（CityWalk）不算大点（下午单大点/晚大点罚不咬），
    # 但 11-05 终裁起同受结束闸：14:00-16:00 收尾在闸内合法，
    # 16:30-18:30 占用越闸计迟（旧「街区可开进傍晚」口径废除）。
    hj = _visit(
        "hj",
        "回民街",
        dur=120,
        tier=8,
        start_time=_t(14, 0),
        end_time=_t(16, 0),
    )
    dm = _visit(
        "dm",
        "大明宫遗址公园",
        dur=240,
        tier=2,
        start_time=_t(9, 0),
        end_time=_t(13, 0),
    )
    sc = plan_score(_plan([dm, hj]))
    assert sc.counts["late_entries"] == 0
    assert sc.counts["afternoon_crowd"] == 0
    assert sc.counts["late_big"] == 0
    assert sc.ok
    hj_late = _visit(
        "hj2",
        "回民街",
        dur=120,
        tier=8,
        start_time=_t(16, 30),
        end_time=_t(18, 30),
    )
    sc2 = plan_score(_plan([dm, hj_late]))
    assert sc2.counts["late_entries"] == 1


# --- 回填配对：大点天优先近旁街区 ----------------------------------------


def _cand(name, city, *, loc, minutes=90, tags=None, source=None, category="sight"):
    return {
        "name": name,
        "city": city,
        "category": category,
        "suggested_duration_min": minutes,
        "location": {"lon": loc[0], "lat": loc[1]},
        "tags": tags or [],
        "source": source,
    }


def _spec(name, city, day, *, loc=None, minutes=90):
    spec = {
        "name": name,
        "city": city,
        "category": "sight",
        "day": day,
        "duration_minutes": minutes,
    }
    if loc is not None:
        spec["location"] = {"lon": loc[0], "lat": loc[1]}
    return spec


def test_rebalance_pairs_big_day_with_nearby_street():
    # day3 已有大点（大明宫 180min）：回填排序把大点近旁（≤6km）的
    # 街区轻点提到队首——「一个大点 + 近距离 CityWalk」的日形，不再
    # 按档位顶格补第二个重磅。
    picked = [_spec("大明宫遗址公园", "西安", 3, loc=(108.96, 34.28), minutes=180)]
    candidates = [
        _cand("兵马俑", "西安", loc=(109.29, 34.38), minutes=240, tags=["5a"]),
        _cand("回民街", "西安", loc=(108.93, 34.27), source="street", minutes=120),
    ]
    out, _notes = PlanningAgent._rebalance_days(picked, candidates, 3, {"西安": (3, 3)})
    names = [s["name"] for s in out]
    assert "回民街" in names
    assert "兵马俑" not in names


def test_rebalance_no_big_day_keeps_tier_order():
    # 无大点锚的天不受配对偏好影响：tier 序照旧（重磅先于街区）。
    picked = [_spec("锚点小点", "西安", 3, loc=(108.96, 34.28), minutes=60)]
    candidates = [
        _cand("兵马俑", "西安", loc=(109.29, 34.38), minutes=180, tags=["5a"]),
        _cand("回民街", "西安", loc=(108.93, 34.27), source="street", minutes=120),
    ]
    out, _notes = PlanningAgent._rebalance_days(picked, candidates, 3, {"西安": (3, 3)})
    names = [s["name"] for s in out]
    # 60+180+腿 或 60+120+腿 均在预算内——档位序先补重磅，街区靠后或
    # 因 4 点/预算闸不补，但绝不能反序（街区先于重磅被选中）。
    if "回民街" in names and "兵马俑" in names:
        assert names.index("兵马俑") < names.index("回民街")


# --- 必去让位清算（2026-11-04 it-b986c4f6 熊猫挂日尾事故） ----------------


def _plan_with(days: list[DayPlan]) -> ItineraryPlan:
    return ItineraryPlan(
        itinerary_id="it-x",
        cities=[d.base_city for d in days],
        days=days,
        assumptions=[],
    )


def _panda_day() -> DayPlan:
    js = _visit(
        "js",
        "金沙遗址博物馆",
        dur=120,
        tier=3,
        start_time=_t(9, 0),
        end_time=_t(11, 0),
    )
    lunch = _visit(
        "lunch",
        "午饭",
        dur=30,
        category="food",
        start_time=_t(11, 30),
        end_time=_t(12, 0),
    )
    wpf = _visit(
        "wpf",
        "望平坊旅游休闲街区",
        dur=90,
        tier=8,
        start_time=_t(12, 0),
        end_time=_t(13, 30),
    )
    dft = _visit(
        "dft",
        "杜甫草堂",
        dur=120,
        tier=3,
        start_time=_t(14, 12),
        end_time=_t(16, 12),
    )
    panda = _visit(
        "panda",
        "成都大熊猫繁育研究基地",
        dur=180,
        tier=3,
        pinned=True,
        poi_id="ct_成都_0",
        opening_hours="07:30-17:00",
    )
    return DayPlan(day=3, base_city="成都", items=[js, lunch, wpf, dft, panda])


def test_room_sweep_evicts_filler_for_pinned_big():
    # 钉住熊猫（180min 大点）被望平坊 12:00 + 杜甫草堂 14:12 顶满下午：
    # 清场挤掉凑数街区、给熊猫留出 12:00 头档整档，且留痕披露。
    from app.services.agent.plan import (
        _day_fixed_windows,
        _must_visit_room_sweep,
        _plan_poi_hours,
        _probe_visit_slot,
    )

    day = _panda_day()
    plan = _plan_with([day])
    notes = _must_visit_room_sweep(plan)
    names = [v.name for v in day.items if isinstance(v, VisitItem)]
    assert "望平坊旅游休闲街区" not in names
    assert notes and any("让位" in n for n in notes)
    fixed, _fixed_tight, _flex_lunches, xfer_windows = _day_fixed_windows(day)
    hours_by_poi = {h.poi_id: h for h in _plan_poi_hours(plan)}
    panda = next(v for v in day.items if v.item_id == "panda")
    t = _probe_visit_slot(
        panda,
        fixed,
        xfer_windows,
        hours_by_poi,
        21 * 60 + 30,
        floor=12 * 60,
        cap_max=13 * 60,
    )
    assert t == 12 * 60


def test_room_sweep_idempotent_when_feasible():
    # 已可行的钉住条目零改动：熊猫自己有时刻时清场不挤任何条目。
    from app.services.agent.plan import _must_visit_room_sweep

    day = _panda_day()
    panda = next(v for v in day.items if v.item_id == "panda")
    panda.start_time = _t(12, 0)
    panda.end_time = _t(15, 0)
    before = [v.name for v in day.items]
    notes = _must_visit_room_sweep(_plan_with([day]))
    after = [v.name for v in day.items]
    assert notes == []
    assert before == after


# --- 兜底排序镜像：必去/大点先排 + 下午单大点 -----------------------------


def test_fallback_schedules_big_before_street():
    # 求解器降级时游标贪心不再让街区轻点抢占 9 点头档：大点先落 09:00。
    from app.services.agent.plan import _fallback_sequence_times

    hj = _visit("hj", "回民街", dur=120, tier=8)
    dm = _visit("dm", "大明宫遗址公园", dur=180, tier=2)
    plan = _plan_with([DayPlan(day=1, base_city="西安", items=[hj, dm])])
    _fallback_sequence_times(plan)
    starts = {v.item_id: _minutes(v) for v in plan.days[0].items if v.start_time}
    assert starts["dm"] == 9 * 60
    assert starts["dm"] < starts["hj"]


def test_fallback_skips_second_afternoon_big():
    # 降级镜像「下午单大点」：下午已有杜甫草堂（14:12 大点锚）时，
    # 第二个大点不再被游标塞进下午——留空交校验提示，而不是三连大点。
    from app.services.agent.plan import _fallback_sequence_times

    js = _visit(
        "js",
        "金沙遗址博物馆",
        dur=120,
        tier=3,
        start_time=_t(9, 0),
        end_time=_t(11, 0),
    )
    wpf = _visit(
        "wpf",
        "望平坊旅游休闲街区",
        dur=90,
        tier=8,
        start_time=_t(12, 0),
        end_time=_t(13, 30),
    )
    dft = _visit(
        "dft",
        "杜甫草堂",
        dur=120,
        tier=3,
        start_time=_t(14, 12),
        end_time=_t(16, 12),
    )
    big2 = _visit("big2", "武侯祠", dur=90, tier=3, best_visit_time="afternoon")
    plan = _plan_with([DayPlan(day=3, base_city="成都", items=[js, wpf, dft, big2])])
    _fallback_sequence_times(plan)
    got = {v.item_id: v for v in plan.days[0].items if isinstance(v, VisitItem)}
    assert got["big2"].start_time is None


# --- 心愿吸收守卫：服务型请求不当愿望 -------------------------------------


def test_service_meta_wish_guard():
    from app.services.agent.plan import _is_service_meta_wish

    assert _is_service_meta_wish("帮我看看天气")
    assert _is_service_meta_wish("帮我看看整体行程")
    assert _is_service_meta_wish("帮我查一下攻略")
    assert _is_service_meta_wish("看看天气")
    # 改排指令整句不是愿望（2026-11-08 成都案 5d978820：整句建行成
    # must_visits 无坐标占位卡）。
    assert _is_service_meta_wish("把成都环球中心加回第4天上午")
    assert _is_service_meta_wish("把环球中心挪到第二天下午")
    assert _is_service_meta_wish("把青城山排到第3天")
    # 具体地点宾语的真愿望不受影响。
    assert not _is_service_meta_wish("看熊猫")
    assert not _is_service_meta_wish("帮我看看熊猫")
    assert not _is_service_meta_wish("成都大熊猫繁育研究基地")
    assert not _is_service_meta_wish("把看熊猫加到心愿单")


# --- 交付闸：钉住未排=硬违规 / 下午双大点=警告 -----------------------------


def test_validate_flags_untimed_pinned_as_error():
    from app.services.itinerary.rules import validate_plan

    panda = _visit(
        "panda",
        "成都大熊猫繁育研究基地",
        dur=180,
        tier=3,
        pinned=True,
        city="成都",
    )
    day = DayPlan(day=3, base_city="成都", items=[panda])
    rep = validate_plan(_plan_with([day]), poi_hours=[])
    hits = [
        v for v in rep.violations if v.rule_id == 19 and v.severity.value == "error"
    ]
    assert hits and "成都大熊猫繁育研究基地" in hits[0].message
    assert not rep.ok


def test_validate_flags_second_afternoon_big_as_warning():
    from app.services.itinerary.rules import validate_plan

    a = _visit(
        "a",
        "大雁塔",
        dur=90,
        tier=2,
        start_time=_t(14, 0),
        end_time=_t(15, 30),
    )
    b = _visit(
        "b",
        "西安城墙",
        dur=90,
        tier=2,
        start_time=_t(15, 30),
        end_time=_t(17, 0),
    )
    rep = validate_plan(
        _plan_with([DayPlan(day=1, base_city="西安", items=[a, b])]), poi_hours=[]
    )
    hits = [
        v for v in rep.violations if v.rule_id == 7 and v.severity.value == "warning"
    ]
    assert hits and "大雁塔" in hits[0].message and "西安城墙" in hits[0].message


def test_fallback_big_site_not_forced_to_noon_anymore():
    """2026-11-14 拍板「IGNORE pinned big site probes from noon rule」：上午
    已被占时，钉住大点不再压到 12:00 起探——远点打车腿（天安门→慕田峪
    80 分钟）填 10:00–12:00 空档，大点 11:20 落位而非正午。"""
    from app.services.agent.plan import _fallback_sequence_times
    from app.services.itinerary.models import GeoPoint

    tam = _visit(
        "tam",
        "天安门广场",
        dur=90,
        tier=1,
        start_time=_t(8, 30),
        end_time=_t(10, 0),
        pinned=True,
        location=GeoPoint(lon=116.4103, lat=39.9115),
    )
    mut = _visit(
        "mut",
        "慕田峪长城",
        dur=180,
        tier=1,
        pinned=True,
        location=GeoPoint(lon=116.5598, lat=40.4267),
    )
    plan = _plan_with([DayPlan(day=1, base_city="北京", items=[tam, mut])])
    _fallback_sequence_times(plan)
    got = {v.item_id: v for v in plan.days[0].items if isinstance(v, VisitItem)}
    assert got["mut"].start_time is not None
    assert _minutes(got["mut"]) < 12 * 60
