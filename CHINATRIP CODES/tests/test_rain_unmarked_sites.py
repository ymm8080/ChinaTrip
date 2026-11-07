# -*- coding: utf-8 -*-
"""未标注室内外点的雨天语义（2026-11-05 拍板「雨天上午不排室外点」）。

线上会话 0bdbbbb1（上海→成都→重庆→上海 8 天，start 11-08）：第 8 天
（11-15）重庆 Open-Meteo 预报小雨，上午 09:00 排磁器口街区（tier8、
PG 库 indoor/rain_ok 全空=unknown）——引擎四层雨闸（整段降权/雨日
硬闸/对调四通道/上午保底）全部只认 rain_ok∈{no,partial}，unknown
静默放行，连「备伞」披露都没有。本组锁：
- 选点层：未标注非王牌点目标天有雨且有干日计数空位 → 挪干日（软
  语义不出局，无干日空位留雨日交对调）；
- 对调层：未标注点落雨日 → 参与四通道对调（hard=False 只换不删，
  无室内可换=保持原排+备伞留痕，不再静默）；
- 上午保底：雨天空上午补点室内（rain_ok=yes）优先，未标注殿后，
  只补到未标注点时留痕备伞；
- 评分层：未标注点落雨日 -5 轻罚（LNS 不把未标注点挪进雨日，也
  不反向硬推）；
- 王牌豁免：tier≤2 未标注点不参与让位/对调（同整段降权口径）。
"""

from app.services.agent.plan import PlanningAgent, _rain_unmarked
from app.services.itinerary.models import DayPlan, ItineraryPlan, VisitItem
from app.services.itinerary.scoring import PEN_RAIN_UNMARKED, plan_score


def _cand(
    name,
    city,
    rain_ok=None,
    *,
    category="sight",
    lon=104.0,
    lat=30.6,
    source="08",
    dur=60,
):
    return {
        "name": name,
        "city": city,
        "category": category,
        "source": source,
        "rain_ok": rain_ok,
        "location": {"lon": lon, "lat": lat},
        "suggested_duration_min": dur,
    }


# ---------------- 判定边界 ----------------


def test_rain_unmarked_boundary():
    # rain_ok 已标注一律不算未标注；未标注行按品类豁免室内类
    assert _rain_unmarked(_cand("甲", "成都", None))
    assert _rain_unmarked(_cand("甲", "成都", ""))
    assert not _rain_unmarked(_cand("甲", "成都", "no"))
    assert not _rain_unmarked(_cand("甲", "成都", "partial"))
    assert not _rain_unmarked(_cand("甲", "成都", "yes"))
    assert not _rain_unmarked(_cand("甲馆", "成都", None, category="museum"))
    assert not _rain_unmarked(_cand("甲馆", "成都", None, category="gallery"))
    assert not _rain_unmarked(_cand("午饭", "成都", None, category="food"))
    assert not _rain_unmarked(_cand("酒店", "成都", None, category="hotel"))
    assert not _rain_unmarked(_cand("演出", "成都", None, category="entertainment"))


# ---------------- 选点层：干日空位让位 ----------------


def test_unmarked_redirects_to_dry_day_when_counter_room():
    # 北簇（雨日1）室内馆+未标注街区：街区目标天有雨、干日2 有计数
    # 空位 → 挪干日（软语义，无披露无出局）
    cands = [
        _cand("甲馆", "成都", "yes", lat=31.5),
        _cand("磁街区", "成都", None, lat=31.5),
        _cand("丙馆", "成都", "yes", lat=30.5),
    ]
    notes: list[str] = []
    picked = PlanningAgent._deterministic_selection(
        cands, 2, {"成都": (1, 2)}, rain_days={"成都": {1}}, notes=notes
    )
    day_of = {p["name"]: p["day"] for p in picked}
    assert day_of["甲馆"] == 1
    assert day_of["磁街区"] == 2
    assert not any("磁街区" in n for n in notes)


def test_unmarked_ace_stays_on_rainy_day():
    # 王牌档（tier≤2）未标注点不参与让位（同整段降权口径：王牌保持
    # tier 梯子原位）——source=5a 落雨日照排
    cands = [
        _cand("王牌街", "成都", None, lat=31.5, source="5a"),
        _cand("丙馆", "成都", "yes", lat=30.5),
    ]
    notes: list[str] = []
    picked = PlanningAgent._deterministic_selection(
        cands, 2, {"成都": (1, 2)}, rain_days={"成都": {1}}, notes=notes
    )
    day_of = {p["name"]: p["day"] for p in picked}
    assert day_of["王牌街"] == 1
    assert not any("王牌街" in n and "备伞" in n for n in notes)


# ---------------- 对调层：落雨日参与四通道 ----------------


def test_unmarked_on_rain_day_swaps_with_dry_day_indoor():
    # 干日2 先被 4 件占满计数（含室内丙馆）→ 北簇未标注街区让位失败
    # 留雨日1 → 对调层 ①单点对调：磁街区 ↔ 丙馆，点名披露含
    # 「室内外未标注」
    # 南簇四件坐标错开 >1.5km（同点行互认并卡会让干日 2 满不了，
    # 验不出对调分支；族卡已废，贴邻同日圈 5km 软偏好同向）。
    cands = [
        _cand("丙馆", "成都", "yes", lat=30.5),
        _cand("丙山", "成都", "no", lat=30.515),
        _cand("丁岭", "成都", "no", lat=30.53),
        _cand("戊峰", "成都", "no", lat=30.545),
        _cand("甲馆", "成都", "yes", lat=31.5),
        _cand("乙馆", "成都", "yes", lat=31.5),
        _cand("磁街区", "成都", None, lat=31.5),
    ]
    notes: list[str] = []
    picked = PlanningAgent._deterministic_selection(
        cands, 2, {"成都": (1, 2)}, rain_days={"成都": {1}}, notes=notes
    )
    day_of = {p["name"]: p["day"] for p in picked}
    assert day_of["磁街区"] == 2
    assert day_of["丙馆"] == 1
    assert any("磁街区" in n and "已对调" in n and "室内外未标注" in n for n in notes)


def test_unmarked_kept_with_umbrella_note_when_nothing_to_swap():
    # 全城无室内可换（干日4 件全露天占满计数）→ 未标注街区留雨日
    # 不删点（hard=False），保持原排+备伞留痕（不再静默）
    # 干日簇四件坐标错开 >1.5km（同点行互认并卡会让干日 2 不满、
    # 磁街区直接挪走，验不出「无干日空位留雨日+备伞」分支；族卡已废，
    # 贴邻同日圈 5km 软偏好同向）。
    cands = [
        _cand("丙山", "成都", "no", lat=30.5),
        _cand("丁岭", "成都", "no", lat=30.515),
        _cand("戊峰", "成都", "no", lat=30.53),
        _cand("己山", "成都", "no", lat=30.545),
        _cand("甲馆", "成都", "yes", lat=31.5),
        _cand("乙馆", "成都", "yes", lat=31.5),
        _cand("磁街区", "成都", None, lat=31.5),
    ]
    notes: list[str] = []
    picked = PlanningAgent._deterministic_selection(
        cands, 2, {"成都": (1, 2)}, rain_days={"成都": {1}}, notes=notes
    )
    day_of = {p["name"]: p["day"] for p in picked}
    # 甲馆/乙馆落雨日1（室内不拦），磁街区同簇也落雨日、无室内可换
    assert day_of["磁街区"] == 1
    assert any("磁街区" in n and "保持原排" in n and "建议备伞" in n for n in notes)


# ---------------- 上午保底：雨天室内优先 ----------------


def _agent() -> PlanningAgent:
    return PlanningAgent(None)


def _day(day=1, city="成都"):
    return DayPlan(day=day, base_city=city, items=[])


def test_morning_fill_rainy_prefers_indoor_over_unmarked():
    # 雨天空上午：候选序未标注在前、室内在后 → 补室内（磁器口案主形态）
    agent = _agent()
    plan = ItineraryPlan(itinerary_id="it1", cities=["成都"], days=[_day()])
    cands = [
        _cand("磁街区", "成都", None, lat=31.5, dur=120),
        _cand("甲馆", "成都", "yes", lat=31.4, dur=90),
    ]
    got = agent._morning_fill(
        plan,
        plan.days[0],
        [],
        cands,
        rain_days={"成都": {1}},
        heavy_rain_days={},
    )
    assert got == "甲馆"


def test_morning_fill_rainy_unmarked_last_resort_disclosed():
    # 室内候选全缺：只补到未标注点 → 照补（上午不许空）+ 假设区留痕备伞
    agent = _agent()
    day = _day()
    plan = ItineraryPlan(itinerary_id="it2", cities=["成都"], days=[day])
    cands = [_cand("磁街区", "成都", None, lat=31.5, dur=120)]
    got = agent._morning_fill(
        plan,
        day,
        [],
        cands,
        rain_days={"成都": {1}},
        heavy_rain_days={},
    )
    assert got == "磁街区"
    assert any("磁街区" in a and "备伞" in a for a in plan.assumptions)


def test_morning_fill_dry_day_keeps_candidate_order():
    # 无雨日不受影响：候选序先到先补（防室内优先误伤干日语义）
    agent = _agent()
    plan = ItineraryPlan(itinerary_id="it3", cities=["成都"], days=[_day()])
    cands = [
        _cand("磁街区", "成都", None, lat=31.5, dur=120),
        _cand("甲馆", "成都", "yes", lat=31.4, dur=90),
    ]
    got = agent._morning_fill(plan, plan.days[0], [], cands)
    assert got == "磁街区"


# ---------------- 评分层：雨日轻罚 ----------------


def _score_plan(rain_ok, category="sight"):
    day = DayPlan(
        day=1,
        base_city="成都",
        items=[
            VisitItem(
                item_id="v1",
                name="甲",
                city="成都",
                day=1,
                duration_minutes=60,
                start_time=None,
                rain_ok=rain_ok,
                category=category,
            )
        ],
    )
    plan = ItineraryPlan(itinerary_id="it4", cities=["成都"], days=[day])
    return plan_score(plan, rain_days={"成都": {1}})


def test_plan_score_rain_unmarked_penalty():
    # 未标注非室内品类落雨日 -5（轻罚）；室内/餐饮/演出不罚
    assert _score_plan(None).soft["rain_exposed"] == -PEN_RAIN_UNMARKED
    assert _score_plan("", category="historic").soft["rain_exposed"] == (
        -PEN_RAIN_UNMARKED
    )
    assert _score_plan("yes").soft["rain_exposed"] == 0
    assert _score_plan(None, category="museum").soft["rain_exposed"] == 0
    assert _score_plan(None, category="food").soft["rain_exposed"] == 0
    assert _score_plan(None, category="entertainment").soft["rain_exposed"] == 0
    # 干日不罚
    plan = ItineraryPlan(itinerary_id="it5", cities=["成都"], days=[_day()])
    got = plan_score(plan, rain_days={"重庆": {1}})
    assert got.soft["rain_exposed"] == 0
