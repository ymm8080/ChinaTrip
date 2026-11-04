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


def test_solver_big_cap_1530_holds_in_solve():
    # 大点加严开场闸在 solver 主路成立：单独大点不可能被排到 15:30 后
    # 开场（普通 60 分钟点仍可 16:00 开场——对照锚）。
    dm = _visit("dm", "大明宫遗址公园", dur=240, tier=2)
    out = solve_day(DayPlan(day=1, base_city="西安", items=[dm]), poi_hours=[])
    assert out is not None
    starts = {v.item_id: _minutes(v) for v in out.items if isinstance(v, VisitItem)}
    assert starts["dm"] <= 15 * 60 + 30
    small = _visit("sm", "小点", dur=60, tier=9)
    out2 = solve_day(DayPlan(day=1, base_city="西安", items=[small]), poi_hours=[])
    assert out2 is not None
    starts2 = {v.item_id: _minutes(v) for v in out2.items if isinstance(v, VisitItem)}
    assert starts2["sm"] <= 16 * 60 + 30


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


def test_scorer_big_start_after_1530_is_hard_violation():
    from app.services.itinerary.scoring import plan_score

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

    # 街区 tier8（CityWalk）16:30 开场合法——正是大点后面配的近游。
    hj = _visit(
        "hj",
        "回民街",
        dur=120,
        tier=8,
        start_time=_t(16, 30),
        end_time=_t(18, 30),
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
