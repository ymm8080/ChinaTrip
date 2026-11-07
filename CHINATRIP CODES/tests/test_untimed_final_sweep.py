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

from app.services.agent.plan import PlanningAgent, drop_dangling_visits
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
