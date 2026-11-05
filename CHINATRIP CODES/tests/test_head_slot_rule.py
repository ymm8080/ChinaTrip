# -*- coding: utf-8 -*-
"""头档距离规则回归（2026-11-05 用户拍板「心愿单或者高排序的景点根据
距离远近可以排早上第一个，或者下午第一个景点」）：

- 兜底层上午头档置换：钉住熊猫（心愿/未排）+ 引擎排的金沙上午头档
  → 熊猫吃 09:00、金沙退让午后（it-84a58984 成渝案 12:01 形态根修）；
- 探不进上午（240min 级、午餐硬窗保不住）→ 原头档归还、熊猫走下午
  头档（正午起探既有规则）——绝不两头空；
- 用户自钉有时刻的头档永不触碰（铁律 19）；
- solver 插入/CP 双路同口径：tier≤2 候选吃上午头档。
"""

from datetime import time as _t

from app.services.agent.plan import _fallback_sequence_times
from app.services.itinerary.models import DayPlan, ItineraryPlan, VisitItem
from app.services.itinerary.solver import insertion_schedule_day, solve_day


def _visit(item_id, name, *, dur, tier=None, **kw):
    base = dict(
        item_id=item_id,
        name=name,
        city="成都",
        day=2,
        duration_minutes=dur,
        tier=tier,
        category="sight",
    )
    base.update(kw)
    return VisitItem(**base)


def _minutes(v: VisitItem) -> int:
    assert v.start_time is not None
    return v.start_time.hour * 60 + v.start_time.minute


def _plan(*days_items):
    days = []
    for i, d in enumerate(days_items):
        if isinstance(d, DayPlan):
            days.append(d)
        else:
            days.append(DayPlan(day=i + 1, base_city="成都", items=list(d)))
    return ItineraryPlan(
        itinerary_id="it-x",
        cities=["成都"],
        days=days,
        assumptions=[],
    )


def _chengdu_day(*, panda_dur=180):
    """成渝案形态：金沙（引擎排 09:00 头档）+ 软钉午餐 + 钉住未排熊猫。
    午餐走软钉（系统摆的餐件，flex 不进固定窗）——与真实管线一致。"""
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
        soft_pin=True,
        start_time=_t(11, 30),
        end_time=_t(12, 0),
    )
    panda = _visit(
        "panda",
        "成都大熊猫繁育研究基地",
        dur=panda_dur,
        tier=2,
        pinned=True,
        poi_id="ct_成都_0",
        opening_hours="07:30-17:00",
    )
    return DayPlan(day=2, base_city="成都", items=[js, lunch, panda])


def test_fallback_pinned_wish_displaces_engine_morning_head():
    plan = _plan(_chengdu_day())
    _fallback_sequence_times(plan)
    got = {v.item_id: v for v in plan.days[0].items if isinstance(v, VisitItem)}
    assert got["panda"].start_time is not None
    assert _minutes(got["panda"]) == 9 * 60  # 熊猫吃上午头档
    assert got["js"].start_time is not None
    assert _minutes(got["js"]) >= 12 * 60  # 金沙退让午后
    assert got["lunch"].start_time is not None  # 午餐硬窗保住


def test_fallback_displacement_reverts_when_panda_cannot_fit():
    # 240min 级：上午装不下（午餐硬窗保不住）→ 原头档归还、熊猫下午头档。
    plan = _plan(_chengdu_day(panda_dur=240))
    _fallback_sequence_times(plan)
    got = {v.item_id: v for v in plan.days[0].items if isinstance(v, VisitItem)}
    assert _minutes(got["js"]) == 9 * 60  # 金沙原位
    assert _minutes(got["panda"]) >= 12 * 60  # 熊猫正午头档
    assert got["lunch"].start_time is not None


def test_fallback_user_pinned_head_untouchable():
    # 金沙为用户自钉（铁律 19）→ 不置换，熊猫走下午头档。
    day = _chengdu_day()
    js = next(v for v in day.items if v.item_id == "js")
    js.pinned = True
    plan = _plan(day)
    _fallback_sequence_times(plan)
    got = {v.item_id: v for v in plan.days[0].items if isinstance(v, VisitItem)}
    assert _minutes(got["js"]) == 9 * 60
    assert _minutes(got["panda"]) >= 12 * 60


def test_insertion_head_candidate_takes_morning_head():
    # 插入主路：tier2 候选先插吃 09:00；tier3 大点退让午后。
    cand = _visit("cand", "武侯祠", dur=90, tier=2)
    big = _visit("big", "杜甫草堂", dur=120, tier=3)
    out = insertion_schedule_day(
        DayPlan(day=1, base_city="成都", items=[big, cand]), poi_hours=[]
    )
    assert out is not None
    starts = {v.item_id: _minutes(v) for v in out.items if isinstance(v, VisitItem)}
    assert starts["cand"] == 9 * 60
    assert starts["big"] >= 12 * 60


def test_cp_head_candidate_first():
    # CP 路（A/B 基准）同口径：候选 P 必须是首个开场观光点。
    cand = _visit("cand", "武侯祠", dur=90, tier=2)
    big = _visit("big", "杜甫草堂", dur=120, tier=3)
    out = solve_day(DayPlan(day=1, base_city="成都", items=[big, cand]), poi_hours=[])
    assert out is not None
    starts = {v.item_id: _minutes(v) for v in out.items if isinstance(v, VisitItem)}
    assert starts["cand"] < starts["big"]
