# -*- coding: utf-8 -*-
"""头档规则回归（2026-11-05 同日二裁定案「上午头档应给优先级更高且
离酒店更远的点」）：

- 置换须有距离证据：酒店锚（日内→同城任日回退）+ 两侧坐标 + P 严格
  更远才换（远点清晨出发跑全天）；缺任何距离数据不换，P 照走「下午
  头档」正午起探（it-84a58984 成渝案 12:01 形态的正规修法）；
- 探不进上午（240min 级、午餐硬窗保不住）→ 原头档归还、P 走下午头
  档——绝不两头空；
- 用户自钉有时刻的头档永不触碰（铁律 19）；
- solver 插入/CP 双路同口径：优先级（钉>tier）定谁吃上午头档。
"""

from datetime import time as _t

from app.services.agent.plan import _fallback_sequence_times
from app.services.itinerary.models import DayPlan, ItineraryPlan, VisitItem
from app.services.itinerary.solver import insertion_schedule_day, solve_day

# 成都真实地理（市中心酒店锚）：熊猫基地 ~10km、金沙 ~7km。
_PANDA_FAR = {"lon": 104.1450, "lat": 30.7330}
_JS_NEAR = {"lon": 104.0100, "lat": 30.6780}
_PANDA_CLOSER = {"lon": 104.0900, "lat": 30.6650}


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


def _hotel(day=2):
    return _visit(
        f"hotel{day}",
        "市中心酒店",
        dur=30,
        category="hotel",
        location={"lon": 104.0810, "lat": 30.6600},
        start_time=_t(21, 0),
        end_time=_t(21, 30),
    )


def _chengdu_day(
    *,
    panda_dur=180,
    with_hotel=True,
    panda_loc=None,
    js_loc=None,
    js_pinned=False,
):
    """成渝案形态：金沙（引擎排 09:00 头档）+ 软钉午餐 + 钉住未排熊猫。
    午餐走软钉（系统摆的餐件，flex 不进固定窗）——与真实管线一致。
    缺省不带坐标：距离数据齐备与否由各测试显式给。"""
    js = _visit(
        "js",
        "金沙遗址博物馆",
        dur=120,
        tier=3,
        start_time=_t(9, 0),
        end_time=_t(11, 0),
        location=js_loc,
        pinned=js_pinned,
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
        location=panda_loc,
    )
    items = [js, lunch, panda]
    if with_hotel:
        items.append(_hotel())
    return DayPlan(day=2, base_city="成都", items=items)


def test_fallback_farther_wish_displaces_morning_head():
    # 距离证据齐备（锚+两侧坐标+熊猫 10km > 金沙 7km）→ 熊猫吃上午头档。
    plan = _plan(_chengdu_day(panda_loc=_PANDA_FAR, js_loc=_JS_NEAR))
    _fallback_sequence_times(plan)
    got = {v.item_id: v for v in plan.days[0].items if isinstance(v, VisitItem)}
    assert _minutes(got["panda"]) == 9 * 60  # 熊猫吃上午头档
    assert _minutes(got["js"]) >= 12 * 60  # 金沙退让午后
    assert got["lunch"].start_time is not None  # 午餐硬窗保住


def test_fallback_no_distance_data_no_displacement():
    # 缺距离数据（无锚/无坐标）→ 不换：金沙原位 09:00，熊猫走下午头档。
    plan = _plan(_chengdu_day())
    _fallback_sequence_times(plan)
    got = {v.item_id: v for v in plan.days[0].items if isinstance(v, VisitItem)}
    assert _minutes(got["js"]) == 9 * 60
    assert _minutes(got["panda"]) >= 12 * 60
    assert got["lunch"].start_time is not None


def test_fallback_closer_candidate_does_not_displace():
    # 熊猫更近（1km < 金沙 7km）→ 不换（上午给更远的点）。
    plan = _plan(_chengdu_day(panda_loc=_PANDA_CLOSER, js_loc=_JS_NEAR))
    _fallback_sequence_times(plan)
    got = {v.item_id: v for v in plan.days[0].items if isinstance(v, VisitItem)}
    assert _minutes(got["js"]) == 9 * 60
    assert _minutes(got["panda"]) >= 12 * 60


def test_fallback_same_city_hotel_anchor_across_days():
    # 日内无酒店 → 同城任日酒店作锚（一次入住多日共用）：证据齐备仍换。
    day2 = _chengdu_day(with_hotel=False, panda_loc=_PANDA_FAR, js_loc=_JS_NEAR)
    plan = _plan(DayPlan(day=1, base_city="成都", items=[_hotel(day=1)]), day2)
    _fallback_sequence_times(plan)
    got = {v.item_id: v for v in plan.days[1].items if isinstance(v, VisitItem)}
    assert _minutes(got["panda"]) == 9 * 60
    assert _minutes(got["js"]) >= 12 * 60


def test_fallback_displacement_reverts_when_panda_cannot_fit():
    # 240min 级：上午装不下（午餐硬窗保不住）→ 原头档归还、熊猫下午头档。
    plan = _plan(_chengdu_day(panda_dur=240, panda_loc=_PANDA_FAR, js_loc=_JS_NEAR))
    _fallback_sequence_times(plan)
    got = {v.item_id: v for v in plan.days[0].items if isinstance(v, VisitItem)}
    assert _minutes(got["js"]) == 9 * 60  # 金沙原位
    assert _minutes(got["panda"]) >= 12 * 60  # 熊猫正午头档
    assert got["lunch"].start_time is not None


def test_fallback_user_pinned_head_untouchable():
    # 金沙为用户自钉（铁律 19）→ 不置换，熊猫走下午头档。
    day = _chengdu_day(panda_loc=_PANDA_FAR, js_loc=_JS_NEAR, js_pinned=True)
    plan = _plan(day)
    _fallback_sequence_times(plan)
    got = {v.item_id: v for v in plan.days[0].items if isinstance(v, VisitItem)}
    assert _minutes(got["js"]) == 9 * 60
    assert _minutes(got["panda"]) >= 12 * 60


def test_insertion_head_candidate_takes_morning_head():
    # 插入主路：tier1 候选先插吃 09:00；tier4（非头档）大点退让午后。
    # 2026-11-13 名录序：头档=国际站/unesco/5A（tier≤3），平台站起非头档。
    cand = _visit("cand", "武侯祠", dur=90, tier=1)
    big = _visit("big", "杜甫草堂", dur=120, tier=4)
    out = insertion_schedule_day(
        DayPlan(day=1, base_city="成都", items=[big, cand]), poi_hours=[]
    )
    assert out is not None
    starts = {v.item_id: _minutes(v) for v in out.items if isinstance(v, VisitItem)}
    assert starts["cand"] == 9 * 60
    assert starts["big"] >= 12 * 60


def test_cp_head_candidate_first():
    # CP 路（A/B 基准）同口径：候选 P 必须是首个开场观光点。
    cand = _visit("cand", "武侯祠", dur=90, tier=1)
    big = _visit("big", "杜甫草堂", dur=120, tier=4)
    out = solve_day(DayPlan(day=1, base_city="成都", items=[big, cand]), poi_hours=[])
    assert out is not None
    starts = {v.item_id: _minutes(v) for v in out.items if isinstance(v, VisitItem)}
    assert starts["cand"] < starts["big"]
