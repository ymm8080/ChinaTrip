# -*- coding: utf-8 -*-
"""无时刻参访卡终闸回归（2026-11-03 用户 Day4 事故：「太平森林公园」
None-None 垫在 19:30《梦回大唐》之后交付，腿标注再画一条 64.2km/949
分钟的演出→公园腿，「FIX PERMANENT FOR ALL SITES」）。

根因三层与本测对应：
①build 终局清算嵌在「转场日清算有产出」条件下——普通日（非转场）
  None-None 卡原样交付 → _finalize_untimed_visits 无条件重解→移除留痕；
②读路径（GET/save）只愈腿间隔不愈无时刻卡——旧会话永久回放
  → drop_untimed_visits 读闸（钉/餐/酒店不动）；
③leg_pairs 链不区分已排/未排——已排演出→未排公园画出巨腿
  → 未排卡断链。
"""

from datetime import time as _t

from app.services.agent.plan import (
    PlanningAgent,
    _fallback_sequence_times,
    drop_dangling_visits,
)
from app.services.itinerary.legs import annotate_legs, leg_pairs
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    TransferItem,
    VisitItem,
)

# 真实库位（session 4b309e Day4 载荷坐标）
XYT = GeoPoint(lon=108.9420, lat=34.2393)  # 小雁塔
XABW = GeoPoint(lon=108.9416, lat=34.2385)  # 西安博物院
SZRB = GeoPoint(lon=108.9466, lat=34.1961)  # 陕西自然博物馆
MHDAT = GeoPoint(lon=108.9400, lat=34.3411)  # 《梦回大唐》
TPGY = GeoPoint(lon=108.6530, lat=33.9102)  # 太平森林公园（鄠邑区 64km 外）


def _incident_day4() -> DayPlan:
    """事故形态复刻：三白点+19:30 演出已排，远郊 180 分钟公园 None-None 垫底。"""
    items = [
        VisitItem(
            item_id="v12",
            name="小雁塔",
            city="西安",
            day=4,
            category="attraction",
            duration_minutes=120,
            start_time=_t(9, 0),
            end_time=_t(11, 0),
            location=XYT,
        ),
        VisitItem(
            item_id="food-lunch-d4",
            name="午饭（自由安排）",
            city="西安",
            day=4,
            category="food",
            duration_minutes=30,
            start_time=_t(11, 30),
            end_time=_t(12, 0),
            soft_pin=True,
        ),
        VisitItem(
            item_id="v13",
            name="西安博物院",
            city="西安",
            day=4,
            category="museum",
            duration_minutes=120,
            start_time=_t(12, 0),
            end_time=_t(14, 0),
            location=XABW,
        ),
        VisitItem(
            item_id="v15",
            name="陕西自然博物馆",
            city="西安",
            day=4,
            category="museum",
            duration_minutes=120,
            start_time=_t(14, 41),
            end_time=_t(16, 41),
            location=SZRB,
        ),
        VisitItem(
            item_id="v19",
            name="《梦回大唐》",
            city="西安",
            day=4,
            category="entertainment",
            best_visit_time="show",
            duration_minutes=80,
            start_time=_t(19, 30),
            end_time=_t(20, 50),
            location=MHDAT,
        ),
        VisitItem(
            item_id="v7",
            name="太平森林公园",
            city="西安",
            day=4,
            category="nature",
            duration_minutes=180,
            location=TPGY,
        ),
    ]
    return DayPlan(day=4, base_city="西安", items=items)


def _plan() -> ItineraryPlan:
    return ItineraryPlan(
        itinerary_id="it-untimed",
        cities=["西安"],
        days=[_incident_day4()],
        assumptions=[],
    )


def _bare_agent(solve_result=None) -> PlanningAgent:
    """跳过 __init__ 的裸 agent：_finalize_untimed_visits 只用 self._solve。"""
    agent = PlanningAgent.__new__(PlanningAgent)
    agent._solve = lambda plan, meal_flex=True, **kw: solve_result  # type: ignore[method-assign]
    return agent


# --- ① build 终闸：普通日 None-None 卡不再交付 ------------------------------


def test_finalize_drops_untimed_park_after_evening_show():
    plan = _plan()
    out = _bare_agent(solve_result=None)._finalize_untimed_visits(plan)
    names = [i.name for i in out.days[0].items]
    assert "太平森林公园" not in names, "远郊公园装不下必须移除留痕，不得垫在演出后交付"
    assert "《梦回大唐》" in names and "小雁塔" in names
    assert any("太平森林公园" in str(a) for a in out.assumptions), "移除必须留痕"


def test_finalize_noop_when_all_timed():
    plan = _plan()
    park = next(i for i in plan.days[0].items if i.item_id == "v7")
    plan.days[0].items.remove(park)
    out = _bare_agent(solve_result=None)._finalize_untimed_visits(plan)
    assert out.assumptions == []


def test_finalize_respects_resolved_plan():
    """CP 重解成功且排上全部时刻→沿用重解结果（不清算）。"""
    plan = _plan()
    solved = _plan()
    park = next(i for i in solved.days[0].items if i.item_id == "v7")
    park.start_time = _t(9, 0)
    park.end_time = _t(12, 0)
    out = _bare_agent(solve_result=solved)._finalize_untimed_visits(plan)
    assert any(i.item_id == "v7" for i in out.days[0].items)
    assert out.assumptions == []


def test_finalize_sweeps_room_for_pinned_panda_after_fillers_timed():
    """2026-11-05 成渝案 d3df5a8（it-32765684 Day2 真实坐标）：solve 把
    凑数点排上时刻（金沙 09:00-11:00/宽窄 12:00-14:30/武侯祠 15:23-16:53）
    后降级兜底，钉住必去熊猫基地 180min 垫到日尾无时刻交付。solve 前的
    前置让位清算探针平凡成功（当时全员未排）零改动——房间被吃掉后
    无人再管。终闸先清场：武侯祠/宽窄让位留痕，熊猫落 12:00-15:00。"""
    day = DayPlan(
        day=2,
        base_city="成都",
        items=[
            VisitItem(
                item_id="v5",
                name="成都金沙遗址博物馆",
                city="成都",
                day=2,
                category="museum",
                duration_minutes=120,
                start_time=_t(9, 0),
                end_time=_t(11, 0),
            ),
            VisitItem(
                item_id="food-lunch-ph-d2",
                name="午饭（自由安排）",
                city="成都",
                day=2,
                category="food",
                duration_minutes=30,
                start_time=_t(11, 30),
                end_time=_t(12, 0),
                soft_pin=True,
            ),
            VisitItem(
                item_id="v6",
                name="宽窄巷子",
                city="成都",
                day=2,
                category="attraction",
                duration_minutes=150,
                start_time=_t(12, 0),
                end_time=_t(14, 30),
            ),
            VisitItem(
                item_id="v7",
                name="武侯祠",
                city="成都",
                day=2,
                category="attraction",
                duration_minutes=90,
                start_time=_t(15, 23),
                end_time=_t(16, 53),
            ),
            VisitItem(
                item_id="v8",
                name="成都大熊猫繁育研究基地",
                city="成都",
                day=2,
                category="zoo",
                duration_minutes=180,
                pinned=True,
            ),
        ],
    )
    plan = ItineraryPlan(
        itinerary_id="it-panda", cities=["成都"], days=[day], assumptions=[]
    )
    out = _bare_agent(solve_result=None)._finalize_untimed_visits(plan)
    d2 = out.days[0]
    panda = next(i for i in d2.items if i.item_id == "v8")
    assert panda.start_time == _t(12, 0) and panda.end_time == _t(15, 0), (
        "钉住必去必须拿到整档时刻，不得无时刻交付"
    )
    names = [i.name for i in d2.items]
    assert "武侯祠" not in names and "宽窄巷子" not in names, "凑数点让位"
    assert "成都金沙遗址博物馆" in names
    jinsha = next(i for i in d2.items if i.item_id == "v5")
    assert jinsha.start_time == _t(9, 0), "已排钉外锚不动"
    lunch = next(i for i in d2.items if i.category == "food")
    assert lunch.start_time == _t(11, 30), "午餐硬窗不动"
    for victim in ("武侯祠", "宽窄巷子"):
        assert any(victim in str(a) and "让位" in str(a) for a in out.assumptions), (
            f"{victim} 让位必须留痕披露"
        )


def test_finalize_sweep_noop_when_pinned_panda_already_timed():
    """幂等：钉住必去已有时刻（用户钉位）→ 终闸零改动零披露。"""
    day = DayPlan(
        day=2,
        base_city="成都",
        items=[
            VisitItem(
                item_id="v8",
                name="成都大熊猫繁育研究基地",
                city="成都",
                day=2,
                category="zoo",
                duration_minutes=180,
                pinned=True,
                start_time=_t(9, 0),
                end_time=_t(12, 0),
            ),
        ],
    )
    plan = ItineraryPlan(
        itinerary_id="it-panda2", cities=["成都"], days=[day], assumptions=[]
    )
    out = _bare_agent(solve_result=None)._finalize_untimed_visits(plan)
    assert out.assumptions == []
    panda = out.days[0].items[0]
    assert panda.start_time == _t(9, 0)


# --- ② 读闸：旧会话打开即清 ----------------------------------------------


def test_read_gate_drops_untimed_keeps_pinned_and_food():
    plan = _plan()
    day = plan.days[0]
    show = next(i for i in day.items if i.item_id == "v19")
    show.pinned = True
    show.start_time = None  # 钉住但未排（铁律 19 面儿）
    notes = drop_dangling_visits(plan)
    names = [i.name for i in day.items]
    assert "太平森林公园" not in names
    assert "《梦回大唐》" in names, "钉点不删"
    assert "午饭（自由安排）" in names, "餐不删"
    assert notes and any("太平森林公园" in str(n) for n in notes)
    assert not any("《梦回大唐》" in str(n) for n in notes)


def test_read_gate_noop_on_clean_plan():
    plan = _plan()
    plan.days[0].items = [i for i in plan.days[0].items if i.item_id != "v7"]
    assert drop_dangling_visits(plan) == []


def test_read_gate_keeps_fully_untimed_day():
    """整日全未排的降级日/骨架日不清——读闸不能把骨架会话读穿成空壳
    （test_plan_dedupe_gate 夹具即全未排形态）。"""
    plan = _plan()
    for i in plan.days[0].items:
        if isinstance(i, VisitItem):
            i.start_time = None
            i.end_time = None
    assert drop_dangling_visits(plan) == []
    names = [i.name for i in plan.days[0].items]
    assert "太平森林公园" in names and "《梦回大唐》" in names


# --- ③ 腿标注：未排卡断链，不再画巨腿 --------------------------------------


def test_leg_pairs_break_chain_at_untimed():
    plan = _plan()
    pairs = leg_pairs(plan)
    legs_from_show = [a.name for a, _b, _km in pairs if a.item_id == "v19"]
    assert legs_from_show == [], "演出后垫的未排公园不得成为腿终点"


def test_annotate_legs_no_bogus_leg_into_untimed():
    plan = _plan()
    annotate_legs(plan)
    show = next(i for i in plan.days[0].items if i.item_id == "v19")
    assert show.distance_to_next_km is None
    assert show.next_walk_minutes is None
    museum = next(i for i in plan.days[0].items if i.item_id == "v13")
    assert museum.distance_to_next_km is not None, "已排链上腿照画"


# --- 回头重试（2026-11-07 用户指令「被裁点同城其他天回头重试」） ----------


def test_finalize_retries_moved_stray_on_other_city_days():
    """挪日线只认首个结构可行日：大块头被挪进满员日（演出钉死傍晚）
    物理无档 → 旧路径终局蒸发，day3 空档再无机会。现口径回头重试：
    已坐日+已试日除外逐日试宿，day3 落位成功（披露「回头改排」）。"""
    xy = GeoPoint(lon=104.06, lat=30.60)

    def _mk(name, day, minutes, hh):
        return VisitItem(
            item_id=f"{name}-{day}",
            name=name,
            city="成都",
            day=day,
            category="attraction",
            duration_minutes=minutes,
            start_time=_t(hh),
            location=xy,
        )

    big = VisitItem(
        item_id="big",
        name="成都环球中心",
        city="成都",
        day=1,
        category="attraction",
        duration_minutes=240,
        location=xy,
    )
    # day1 到达日：落地地板 14:30 + 武侯祠占 14:30-16:00 → 240min 大块
    # 越大点 15:30 带无档；day2 结构可行（3 件）但傍晚演出钉死、fallback
    # 排不出；day3 只有一件 → rehome 挪 day2 仍无时刻，回头重试落 day3。
    day1 = DayPlan(
        day=1,
        base_city="成都",
        items=[
            TransferItem(
                item_id="t1",
                day=1,
                seq=1,
                mode="train",
                from_city="上海",
                to_city="成都",
                start_time=_t(8, 0),
                end_time=_t(12, 0),
            ),
            _mk("武侯祠", 1, 90, 14),
            big,
        ],
    )
    day2 = DayPlan(
        day=2,
        base_city="成都",
        items=[
            _mk("戊", 2, 120, 9),
            _mk("己", 2, 120, 11),
            VisitItem(
                item_id="show-2",
                name="蜀兿剧院",
                city="成都",
                day=2,
                category="entertainment",
                duration_minutes=90,
                start_time=_t(17, 0),
                end_time=_t(18, 30),
                pinned=True,
                location=xy,
            ),
        ],
    )
    day3 = DayPlan(
        day=3,
        base_city="成都",
        items=[_mk("辛", 3, 90, 9)],
    )
    for v in day1.items:
        v.day = 1
    for v in day2.items:
        v.day = 2
    plan = ItineraryPlan(
        itinerary_id="it-retry",
        cities=["上海", "成都"],
        days=[day1, day2, day3],
        assumptions=[],
    )
    out = _bare_agent(solve_result=None)._finalize_untimed_visits(plan)
    big_final = next(i for d in out.days for i in d.items if i.item_id == "big")
    # day2 被实位探针拒（演出 17:00 封傍晚档）→ rehome 多日宿主扫描
    # 直接落 day3；若探针过了而 fallback 仍排不出，回头重试循环兜底
    # （真实东郊记忆案的分歧态）。两条路都不许蒸发。
    assert big_final.day == 3
    assert big_final.start_time is not None
    assert any(("挪至第3天" in str(a) or "回头改排" in str(a)) for a in out.assumptions)
    assert not any(
        "已从行程移除" in str(a) and "成都环球中心" in str(a) for a in out.assumptions
    )


# --- 让位留痕 plan.unplaced + 必去跨日救生（2026-11-11 拍板「可替代品跨品
# 类：想排没排进去的景点放右边」） -------------------------------------------


def test_sweep_records_unplaced_yield_must():
    """同日让位清算挤掉的凑数点必须结构化留痕 plan.unplaced（reason=
    yield_must，day_hint=被挤日）——装配期据此作「想去」chip 落被挤日。"""
    day = DayPlan(
        day=2,
        base_city="成都",
        items=[
            VisitItem(
                item_id="v5",
                name="成都金沙遗址博物馆",
                city="成都",
                day=2,
                category="museum",
                duration_minutes=120,
                start_time=_t(9, 0),
                end_time=_t(11, 0),
            ),
            VisitItem(
                item_id="v6",
                name="宽窄巷子",
                city="成都",
                day=2,
                category="attraction",
                duration_minutes=150,
                start_time=_t(12, 0),
                end_time=_t(14, 30),
            ),
            VisitItem(
                item_id="v8",
                name="成都大熊猫繁育研究基地",
                city="成都",
                day=2,
                category="zoo",
                duration_minutes=180,
                pinned=True,
            ),
        ],
    )
    plan = ItineraryPlan(
        itinerary_id="it-unplaced", cities=["成都"], days=[day], assumptions=[]
    )
    out = _bare_agent(solve_result=None)._finalize_untimed_visits(plan)
    by_name = {u.name: u for u in out.unplaced}
    assert "宽窄巷子" in by_name, "被挤点必须进 unplaced"
    assert by_name["宽窄巷子"].reason == "yield_must"
    assert by_name["宽窄巷子"].day_hint == 2


def _greedy_solve(max_minutes: int):
    """假 _solve：无时刻参访按最早空档贪心落时刻，超过 max_minutes 的
    条目永远排不上（模拟物理装不下）。"""

    def _solve(plan, meal_flex=True, **kw):
        for day in plan.days:
            busy = []
            for v in day.items:
                if (
                    isinstance(v, VisitItem)
                    and v.start_time is not None
                    and v.end_time is not None
                ):
                    busy.append(
                        (
                            v.start_time.hour * 60 + v.start_time.minute,
                            v.end_time.hour * 60 + v.end_time.minute,
                        )
                    )
            for v in day.items:
                if not (
                    isinstance(v, VisitItem)
                    and v.start_time is None
                    and (v.category or "") not in ("food", "hotel")
                ):
                    continue
                dur = v.duration_minutes or 90
                if dur > max_minutes:
                    continue
                s = 9 * 60
                while s + dur <= 21 * 60 + 30:
                    clash = next((b for b in busy if b[0] < s + dur and s < b[1]), None)
                    if clash is None:
                        v.start_time = _t(s // 60, s % 60)
                        v.end_time = _t((s + dur) // 60, (s + dur) % 60)
                        busy.append((s, s + dur))
                        break
                    s = clash[1]
        return plan

    return _solve


def _rescue_plan() -> ItineraryPlan:
    """钉住必去 300min 在同日物理装不下（演出钉死傍晚+大点 13:00 起始
    闸），同城次日全空——跨日救生应把必去挪次日落时刻。"""
    xy = GeoPoint(lon=104.06, lat=30.60)
    day1 = DayPlan(
        day=1,
        base_city="成都",
        items=[
            VisitItem(
                item_id="f1",
                name="凑数点甲",
                city="成都",
                day=1,
                category="attraction",
                duration_minutes=120,
                start_time=_t(9, 0),
                end_time=_t(11, 0),
                location=xy,
            ),
            VisitItem(
                item_id="lunch-1",
                name="午饭（自由安排）",
                city="成都",
                day=1,
                category="food",
                duration_minutes=30,
                start_time=_t(12, 0),
                end_time=_t(12, 30),
                soft_pin=True,
            ),
            VisitItem(
                item_id="f2",
                name="凑数点乙",
                city="成都",
                day=1,
                category="attraction",
                duration_minutes=120,
                start_time=_t(14, 0),
                end_time=_t(16, 0),
                location=xy,
            ),
            VisitItem(
                item_id="show-1",
                name="某钉死演出",
                city="成都",
                day=1,
                category="entertainment",
                best_visit_time="show",
                duration_minutes=90,
                start_time=_t(17, 0),
                end_time=_t(18, 30),
                pinned=True,
                location=xy,
            ),
            VisitItem(
                item_id="must-1",
                name="某必去大点",
                city="成都",
                day=1,
                category="attraction",
                duration_minutes=300,
                pinned=True,
                must=True,
                location=xy,
            ),
        ],
    )
    day2 = DayPlan(day=2, base_city="成都", items=[])
    return ItineraryPlan(
        itinerary_id="it-rescue", cities=["成都"], days=[day1, day2], assumptions=[]
    )


def test_crossday_rescue_moves_pinned_must_to_feasible_day():
    plan = _rescue_plan()
    agent = PlanningAgent.__new__(PlanningAgent)
    agent._solve = _greedy_solve(max_minutes=400)  # type: ignore[method-assign]
    out = agent._finalize_untimed_visits(plan)
    must = next(i for d in out.days for i in d.items if i.item_id == "must-1")
    assert must.day == 2, "同城次日可行时必须跨日救生，不得灰卡终局"
    assert must.start_time is not None
    assert any("救生改排" in str(a) for a in out.assumptions)
    d1_names = [i.name for i in out.days[0].items]
    assert "凑数点甲" in d1_names and "某钉死演出" in d1_names, (
        "救生全有全无：失败日原样不动"
    )


def test_crossday_rescue_rolls_back_when_target_infeasible():
    """目标日也装不下（假 solve 对 300min 恒排不上）→ 弃克隆原样归还，
    钉住必去留灰卡+披露，绝不留半拉子让位。"""
    plan = _rescue_plan()
    agent = PlanningAgent.__new__(PlanningAgent)
    agent._solve = _greedy_solve(max_minutes=240)  # type: ignore[method-assign]
    out = agent._finalize_untimed_visits(plan)
    must = next(i for d in out.days for i in d.items if i.item_id == "must-1")
    assert must.day == 1 and must.start_time is None, "不可行即回滚"
    assert not any("救生改排" in str(a) for a in out.assumptions)
    d1_names = [i.name for i in out.days[0].items]
    assert "凑数点甲" in d1_names and "凑数点乙" in d1_names, "回滚不得白挤"


def test_crossday_rescue_repins_must_and_rigidifies_pinned_meals():
    """救生采纳后必去按落档时刻回钉（pinned=True，2026-11-11 铁律 19
    口径：用户钉的是「在册必去」，落档时刻即新钉点）；钉住具名餐卡试宿
    前转刚性（可挪不可删）——否则求解器窗满丢餐把钉住宴/餐蒸发成灰卡
    （读闸保钉住卡，灰卡永留）；未钉软锚餐维持可滑可丢。"""
    plan = _rescue_plan()
    banquet = VisitItem(
        item_id="banquet-1",
        name="某钉住宴秀",
        city="成都",
        day=2,
        category="food",
        duration_minutes=90,
        start_time=_t(12, 30),
        end_time=_t(14, 0),
        pinned=True,
        soft_pin=True,
    )
    plan.days[1].items.append(banquet)
    seen: dict[str, bool] = {}
    base_solve = _greedy_solve(max_minutes=400)

    def _spy_solve(p, meal_flex=True, **kw):
        for d in p.days:
            for v in d.items:
                if isinstance(v, VisitItem) and v.item_id == "banquet-1":
                    seen["soft_pin_at_solve"] = bool(v.soft_pin)
        return base_solve(p, meal_flex=meal_flex, **kw)

    agent = PlanningAgent.__new__(PlanningAgent)
    agent._solve = _spy_solve  # type: ignore[method-assign]
    out = agent._finalize_untimed_visits(plan)
    must = next(i for d in out.days for i in d.items if i.item_id == "must-1")
    assert must.start_time is not None and must.pinned is True, (
        "采纳后必须按落档时刻回钉"
    )
    assert seen.get("soft_pin_at_solve") is False, "钉住餐试宿前须转刚性（可挪不可删）"


def test_sweep_evicts_unpinned_show_but_never_pinned_show():
    """2026-11-11 拍板「必去/手建优先于梯队」：未钉凑数演出在钉住必去
    面前照让（让位留痕 plan.unplaced，可经「想去」chip 加回）；钉住演出
    （已锁场次）永不让位。"""
    day = DayPlan(
        day=2,
        base_city="成都",
        items=[
            VisitItem(
                item_id="f1",
                name="某凑数点",
                city="成都",
                day=2,
                category="attraction",
                duration_minutes=180,
                start_time=_t(9, 0),
                end_time=_t(12, 0),
            ),
            VisitItem(
                item_id="e1",
                name="某未钉演出",
                city="成都",
                day=2,
                category="entertainment",
                best_visit_time="show",
                duration_minutes=90,
                start_time=_t(13, 0),
                end_time=_t(14, 30),
            ),
            VisitItem(
                item_id="e2",
                name="某钉住演出",
                city="成都",
                day=2,
                category="entertainment",
                best_visit_time="show",
                duration_minutes=90,
                start_time=_t(17, 0),
                end_time=_t(18, 30),
                pinned=True,
            ),
            VisitItem(
                item_id="v8",
                name="某必去大点",
                city="成都",
                day=2,
                category="attraction",
                duration_minutes=180,
                pinned=True,
                must=True,
            ),
        ],
    )
    plan = ItineraryPlan(
        itinerary_id="it-show-shield", cities=["成都"], days=[day], assumptions=[]
    )
    out = _bare_agent(solve_result=None)._finalize_untimed_visits(plan)
    by_name = {u.name: u for u in out.unplaced}
    assert "某未钉演出" in by_name, "未钉凑数演出在钉住必去面前照让"
    assert by_name["某未钉演出"].reason == "yield_must"
    d2 = next(d for d in out.days if d.day == 2)
    kept = {i.name: i for i in d2.items}
    assert "某钉住演出" in kept and kept["某钉住演出"].start_time == _t(17, 0), (
        "钉住演出已锁场次，永不让位"
    )


# --- 2026-11-13「到达与出发日只安排一项活动」用户拍板 -------------------------
# 根案：西安 5 日 day1 = 曲江艺术博物馆（钉住必去 14:30）+ 陕西历史博物馆
# （具名钉住必去无时刻灰卡）——「两项」。三病根类级收口：
# ① _must_visit_crossday_rescue 的 v.name not in protect 精确名闸把具名
#   必去挡在验证制救生门外（灵隐寺案同病第二现场）→ 灰卡滞留端点日；
# ② 救生候选日原序自家日先行，钉住件落端点日=上限闸无解的新违规；
# ③ 转场日扫的滞留披露前置运行，救生成功后旧披露成反向信息。


def test_rescue_includes_protect_named_must():
    """具名必去（protect 在册）不再被精确名闸挡在救生门外：钉住必去
    无时刻时照样走克隆试宿通道（11-13 拍板「点名必排，排不上删其它
    腾位」——裸挪禁，验证制救生必达）。"""
    plan = _rescue_plan()
    agent = PlanningAgent.__new__(PlanningAgent)
    agent._solve = _greedy_solve(max_minutes=400)  # type: ignore[method-assign]
    out, notes = agent._must_visit_crossday_rescue(plan, protect={"某必去大点"})
    must = next(i for d in out.days for i in d.items if i.item_id == "must-1")
    assert must.day == 2 and must.start_time is not None, (
        "具名必去无时刻必须跨日救生，不得灰卡终局"
    )
    assert any("救生改排" in n for n in notes)


def _departure_day_plan() -> ItineraryPlan:
    """离城日（day3 17:00 出发腿）钉住必去无时刻，同城 day2 全空——
    救生必须先试非端点日，不得自家日（端点）先行落档。"""
    xy = GeoPoint(lon=104.06, lat=30.60)
    day1 = DayPlan(
        day=1,
        base_city="成都",
        items=[
            TransferItem(
                item_id="t-in",
                day=1,
                seq=1,
                mode="train",
                from_city="上海",
                to_city="成都",
                start_time=_t(8, 0),
                end_time=_t(12, 0),
            ),
        ],
    )
    day2 = DayPlan(day=2, base_city="成都", items=[])
    day3 = DayPlan(
        day=3,
        base_city="成都",
        items=[
            TransferItem(
                item_id="t-out",
                day=3,
                seq=1,
                mode="train",
                from_city="成都",
                to_city="上海",
                start_time=_t(17, 0),
                end_time=_t(20, 0),
            ),
            VisitItem(
                item_id="must-d3",
                name="离城日必去",
                city="成都",
                day=3,
                category="attraction",
                duration_minutes=90,
                pinned=True,
                must=True,
                location=xy,
            ),
        ],
    )
    return ItineraryPlan(
        itinerary_id="it-ep-order",
        cities=["上海", "成都", "上海"],
        days=[day1, day2, day3],
        assumptions=[],
    )


def test_rescue_prefers_non_endpoint_day():
    """救生候选日端点日排最后：自家离城日试宿成功也不采纳——上限闸
    对钉住件无解，先落端点日=把灰卡换成新违规（用户可见「两项」）。"""
    plan = _departure_day_plan()
    agent = PlanningAgent.__new__(PlanningAgent)
    agent._solve = _greedy_solve(max_minutes=400)  # type: ignore[method-assign]
    out, _notes = agent._must_visit_crossday_rescue(plan, protect={"离城日必去"})
    must = next(i for d in out.days for i in d.items if i.item_id == "must-d3")
    assert must.day == 2 and must.start_time is not None, (
        "非端点日可行时必须落非端点日，不得自家离城日先行"
    )


def test_rescue_moves_timed_endpoint_stay_violator():
    """11-13「出发日和到达日一样」拍板锚：已排（timed）钉住必去吃
    端点日违例（>80min 大景点时间/距锚 >8km）时，不裸挪——进验证制
    救生链跨日改排；同日重解无解（pinned 时刻=CP 固定档）只试跨日。"""
    xy = GeoPoint(lon=104.06, lat=30.60)
    day1 = DayPlan(
        day=1,
        base_city="成都",
        items=[
            TransferItem(
                item_id="t-in",
                day=1,
                seq=1,
                mode="train",
                from_city="上海",
                to_city="成都",
                start_time=_t(8, 0),
                end_time=_t(12, 0),
            ),
        ],
    )
    day2 = DayPlan(day=2, base_city="成都", items=[])
    day3 = DayPlan(
        day=3,
        base_city="成都",
        items=[
            TransferItem(
                item_id="t-out",
                day=3,
                seq=1,
                mode="train",
                from_city="成都",
                to_city="上海",
                start_time=_t(17, 0),
                end_time=_t(20, 0),
            ),
            VisitItem(
                item_id="must-d3",
                name="离城日大点",
                city="成都",
                day=3,
                category="attraction",
                duration_minutes=180,  # >80min=大景点时间违例翼
                pinned=True,
                must=True,
                location=xy,
                start_time=_t(9, 0),
                end_time=_t(12, 0),
            ),
        ],
    )
    plan = ItineraryPlan(
        itinerary_id="it-ep-stay",
        cities=["上海", "成都", "上海"],
        days=[day1, day2, day3],
        assumptions=[],
    )
    agent = PlanningAgent.__new__(PlanningAgent)
    agent._solve = _greedy_solve(max_minutes=400)  # type: ignore[method-assign]
    out, notes = agent._must_visit_crossday_rescue(plan, protect={"离城日大点"})
    must = next(i for d in out.days for i in d.items if i.item_id == "must-d3")
    assert must.day == 2 and must.start_time is not None, (
        "端点日违例必去必须验证制救生到非端点日，不得原天滞留"
    )
    assert must.pinned is True, "救生采纳后按解出时刻回钉"
    assert any("超出端点日轻量口径" in n for n in notes), "违例救生留痕披露"


def test_rescue_prunes_stale_disclosure_but_keeps_stray_mate():
    """转场日扫的滞留披露在本闸之前跑：救生成功后按名剥除token——
    披露行聚合同日多名时不得整行丢弃（同伴滞留披露被吃掉=静默）。"""
    xy = GeoPoint(lon=104.06, lat=30.60)
    day1 = DayPlan(
        day=1,
        base_city="成都",
        items=[
            TransferItem(
                item_id="t-in",
                day=1,
                seq=1,
                mode="train",
                from_city="上海",
                to_city="成都",
                start_time=_t(8, 0),
                end_time=_t(12, 0),
            ),
            VisitItem(
                item_id="must-a",
                name="救生甲",
                city="成都",
                day=1,
                category="attraction",
                duration_minutes=90,
                pinned=True,
                must=True,
                location=xy,
            ),
            VisitItem(
                item_id="must-b",
                name="滞留乙",
                city="成都",
                day=1,
                category="attraction",
                duration_minutes=3000,  # 物理装不下：greedy 永不落档
                pinned=True,
                must=True,
                location=xy,
            ),
        ],
    )
    day2 = DayPlan(day=2, base_city="成都", items=[])
    plan = ItineraryPlan(
        itinerary_id="it-prune",
        cities=["上海", "成都"],
        days=[day1, day2],
        assumptions=[
            "必去 「救生甲」、「滞留乙」 钉在第1天（转场日）但排不上时刻，"
            "请告诉我换天或换时刻"
        ],
    )
    agent = PlanningAgent.__new__(PlanningAgent)
    agent._solve = _greedy_solve(max_minutes=400)  # type: ignore[method-assign]
    out, _notes = agent._must_visit_crossday_rescue(plan, protect={"救生甲", "滞留乙"})
    a = next(i for d in out.days for i in d.items if i.item_id == "must-a")
    assert a.day == 2 and a.start_time is not None
    b = next(i for d in out.days for i in d.items if i.item_id == "must-b")
    assert b.day == 1 and b.start_time is None, "装不下即回滚留灰卡"
    stale_a = [
        str(x) for x in out.assumptions if "救生甲" in str(x) and "排不上时刻" in str(x)
    ]
    assert stale_a == [], "救生成功后旧滞留披露必须剥除"
    kept_b = [
        str(x) for x in out.assumptions if "滞留乙" in str(x) and "排不上时刻" in str(x)
    ]
    assert kept_b and "救生甲" not in kept_b[0], "同伴滞留披露按名剥token后保留"


def test_rescue_includes_pinned_untimed_show():
    """钉住演出无时刻（端点日转场腿占死晚窗，演出让位/场次链管不到
    钉住件）一并进救生：同城非端点日试宿落场；protect 在册不豁免。"""
    xy = GeoPoint(lon=104.06, lat=30.60)
    day1 = DayPlan(
        day=1,
        base_city="成都",
        items=[
            TransferItem(
                item_id="t-in",
                day=1,
                seq=1,
                mode="train",
                from_city="上海",
                to_city="成都",
                start_time=_t(8, 0),
                end_time=_t(12, 0),
            ),
            VisitItem(
                item_id="show-1",
                name="某钉住演出",
                city="成都",
                day=1,
                category="entertainment",
                best_visit_time="show",
                duration_minutes=90,
                pinned=True,
                must=True,
                location=xy,
            ),
        ],
    )
    day2 = DayPlan(day=2, base_city="成都", items=[])
    plan = ItineraryPlan(
        itinerary_id="it-show-rescue",
        cities=["上海", "成都"],
        days=[day1, day2],
        assumptions=[],
    )
    agent = PlanningAgent.__new__(PlanningAgent)
    agent._solve = _greedy_solve(max_minutes=400)  # type: ignore[method-assign]
    out, _notes = agent._must_visit_crossday_rescue(plan, protect={"某钉住演出"})
    show = next(i for d in out.days for i in d.items if i.item_id == "show-1")
    assert show.day == 2 and show.start_time is not None, (
        "钉住演出无时刻必须救生落场，不得灰卡滞留端点日"
    )


# --- 2026-11-13 拍板「心愿单必须达成，可删其它不重要景点」兑现锚 -------------


def test_finalize_fallback_runs_after_solve_success_for_pinned_must():
    """CP 重解返回「成功」计划≠全员落档：钉住必去在 solve 无排程域
    （room_sweep 腾位后仍灰卡）时，成功分支此前跳过兜底链直送终局
    （陕历博返程日 None-None 案）。只要还有未排参访就必须补一轮兜底。"""
    xy = GeoPoint(lon=104.06, lat=30.60)
    day = DayPlan(
        day=1,
        base_city="成都",
        items=[
            VisitItem(
                item_id="m1",
                name="某钉住必去",
                city="成都",
                day=1,
                category="museum",
                duration_minutes=120,
                pinned=True,
                must=True,
                location=xy,
            ),
        ],
    )
    plan = ItineraryPlan(
        itinerary_id="it-fb-after-ok", cities=["成都"], days=[day], assumptions=[]
    )
    agent = PlanningAgent.__new__(PlanningAgent)
    # 假 solve 恒返回计划（≠None=「成功」）但 120min 条目在 max=60 下
    # 永不落档——正是旧码跳过兜底的形态。
    agent._solve = _greedy_solve(max_minutes=60)  # type: ignore[method-assign]
    out = agent._finalize_untimed_visits(plan)
    must = next(i for d in out.days for i in d.items if i.item_id == "m1")
    assert must.start_time is not None, "solve 成功≠全员落档：钉住必去必须兜底落时刻"


def test_fallback_never_skips_pinned_second_afternoon_big():
    """「第二个下午大点」软跳只约束普通卡：钉住必去即使与本日已排
    下午大点相距 >5km（非贴邻），兜底也恒放行落位（点名必排，排不上
    删弱件腾位——room_sweep 已先行腾位，软让位不得再拦）。"""
    xy_a = GeoPoint(lon=104.06, lat=30.60)  # 城区锚
    xy_b = GeoPoint(lon=104.10, lat=30.65)  # 距锚约 6.7km（>5km 非贴邻、短腿可达）
    day = DayPlan(
        day=1,
        base_city="成都",
        items=[
            VisitItem(
                item_id="am1",
                name="某上午小点",
                city="成都",
                day=1,
                category="attraction",
                duration_minutes=60,
                start_time=_t(9, 0),
                end_time=_t(10, 0),
                location=xy_a,
            ),
            VisitItem(
                item_id="big1",
                name="某下午大点",
                city="成都",
                day=1,
                category="attraction",
                duration_minutes=90,
                start_time=_t(13, 0),
                end_time=_t(14, 30),
                location=xy_a,
            ),
            VisitItem(
                item_id="must2",
                name="某钉住必去大点",
                city="成都",
                day=1,
                category="attraction",
                duration_minutes=90,
                pinned=True,
                must=True,
                location=xy_b,
            ),
        ],
    )
    plan = ItineraryPlan(
        itinerary_id="it-fb-pinned-big", cities=["成都"], days=[day], assumptions=[]
    )
    _fallback_sequence_times(plan)
    must2 = next(i for i in plan.days[0].items if i.item_id == "must2")
    assert must2.start_time is not None, (
        "钉住必去不受第二个下午大点软跳约束，兜底必须落位"
    )
