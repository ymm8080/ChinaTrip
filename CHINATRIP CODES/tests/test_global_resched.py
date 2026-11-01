# -*- coding: utf-8 -*-
"""S2 跨天全局重排（LNS + destroy-repair）单测——设计稿 §7-S2 七件套。

设计依据：《跨日全局优化方案调研-2026-11-01》（评分驱动邻域搜索
=TOPTW 主流且 SOTA；ELNS destroy-repair 与 max-min 均衡项已吸收）。
"""

from datetime import time

from app.services.agent.plan import PlanningAgent
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    VisitItem,
)
from app.services.itinerary.scoring import plan_score


class _NoLLM:
    async def chat(self, *a, **k):  # pragma: no cover - 不应被调用
        raise AssertionError("llm must not be called")


def _xian_fixture():
    """用户 4f228cfb 案形状：day3 雨天空上午（软午餐+华清池 240+未排
    《秦俑情》），day4 兵马俑 09:00 + 钟楼 11:00。"""
    lunch = VisitItem(
        item_id="lunch-3",
        name="午饭（自由安排）",
        category="food",
        city="西安",
        day=3,
        start_time=time(12, 0),
        end_time=time(13, 0),
        duration_minutes=60,
        pinned=True,
        soft_pin=True,
    )
    hqc = VisitItem(
        item_id="v-hqc",
        name="临潼区华清池景区",
        category="attraction",
        city="西安",
        day=3,
        rain_ok="no",
        start_time=time(13, 0),
        end_time=time(17, 0),
        duration_minutes=240,
        location=GeoPoint(lon=109.21, lat=34.36),
    )
    qyq = VisitItem(
        item_id="v-qyq",
        name="《秦俑情》",
        category="entertainment",
        city="西安",
        day=3,
        rain_ok="yes",
        best_visit_time="show",
        opening_hours="多场（约11:00/14:00/17:00）",
        duration_minutes=80,
        location=GeoPoint(lon=109.28, lat=34.38),
    )
    bmy = VisitItem(
        item_id="v-bmy",
        name="秦始皇兵马俑博物馆",
        category="attraction",
        city="西安",
        day=4,
        rain_ok="yes",
        best_visit_time="any",
        start_time=time(9, 0),
        end_time=time(10, 30),
        duration_minutes=90,
        location=GeoPoint(lon=109.27, lat=34.38),
    )
    zl = VisitItem(
        item_id="v-zl",
        name="钟楼",
        category="sight",
        city="西安",
        day=4,
        rain_ok="yes",
        best_visit_time="any",
        start_time=time(11, 0),
        end_time=time(12, 0),
        duration_minutes=60,
        location=GeoPoint(lon=108.94, lat=34.26),
    )
    day3 = DayPlan(day=3, base_city="西安", items=[lunch, hqc, qyq])
    day4 = DayPlan(day=4, base_city="西安", items=[bmy, zl])
    return ItineraryPlan(itinerary_id="it1", cities=["西安"], days=[day3, day4])


def _picked():
    return [
        {"name": "临潼区华清池景区"},
        {"name": "《秦俑情》"},
        {"name": "秦始皇兵马俑博物馆"},
        {"name": "钟楼"},
    ]


def _slb():
    return {
        "name": "陕西历史博物馆",
        "city": "西安",
        "category": "museum",
        "source_poi_id": "4a_slb",
        "suggested_duration_min": 120,
        "rain_ok": "yes",
        "best_visit_time": "any",
        "location": {"lon": 108.95, "lat": 34.24},
    }


RAIN = {"西安": {3, 4}}


def test_lns_repairs_untimed_show_and_blank_morning():
    agent = PlanningAgent(_NoLLM())
    plan = _xian_fixture()
    base = plan_score(plan, rain_days=RAIN)
    assert base.hard["untimed"] == -100
    assert base.hard["blank_morning"] == -80

    moves, b, f = agent._global_resched(plan, _picked(), [_slb()], rain_days=RAIN)

    assert moves, "应当找到改进移动"
    assert f > b == base.total
    final = plan_score(plan, rain_days=RAIN)
    assert final.hard["untimed"] == 0
    assert final.hard["blank_morning"] == 0
    assert f == final.total
    names = {i.name for d in plan.days for i in d.items if isinstance(i, VisitItem)}
    assert {"临潼区华清池景区", "《秦俑情》", "秦始皇兵马俑博物馆", "钟楼"} <= names
    all_items = [i for d in plan.days for i in d.items if isinstance(i, VisitItem)]
    qyq = next(i for i in all_items if i.name == "《秦俑情》")
    assert qyq.start_time is not None  # 演出落上真场次


def test_lns_identity_on_green_plan():
    agent = PlanningAgent(_NoLLM())
    day = DayPlan(
        day=1,
        base_city="西安",
        items=[
            VisitItem(
                item_id="a",
                name="a",
                city="西安",
                day=1,
                duration_minutes=120,
                start_time=time(9, 0),
                end_time=time(11, 0),
            ),
            VisitItem(
                item_id="l",
                name="午饭",
                category="food",
                city="西安",
                day=1,
                duration_minutes=60,
                start_time=time(12, 0),
                end_time=time(13, 0),
                pinned=True,
                soft_pin=True,
            ),
            VisitItem(
                item_id="b",
                name="b",
                city="西安",
                day=1,
                duration_minutes=60,
                start_time=time(14, 0),
                end_time=time(15, 0),
            ),
        ],
    )
    plan = ItineraryPlan(itinerary_id="it1", cities=["西安"], days=[day])
    moves, b, f = agent._global_resched(plan, [], [])
    assert moves == []
    assert b == f == 0


def test_lns_guards_protect_pinned():
    agent = PlanningAgent(_NoLLM())
    plan = _xian_fixture()
    for d in plan.days:
        for i in d.items:
            if isinstance(i, VisitItem):
                i.pinned = True  # 全钉：无算子可用

    moves, b, f = agent._global_resched(plan, _picked(), [_slb()], rain_days=RAIN)

    assert moves == []
    assert b == f


def test_lns_env_switch_off(monkeypatch):
    monkeypatch.setenv("CHINATRIP_GLOBAL_RESCHED", "off")
    agent = PlanningAgent(_NoLLM())
    plan = _xian_fixture()

    moves, b, f = agent._global_resched(plan, _picked(), [_slb()], rain_days=RAIN)

    assert moves == [] and b == 0 and f == 0
    qyq = next(i for i in plan.days[0].items if i.name == "《秦俑情》")
    assert qyq.start_time is None  # 未被触动


def test_lns_eval_budget_zero_is_identity():
    agent = PlanningAgent(_NoLLM())
    plan = _xian_fixture()
    before = plan.model_dump()

    moves, _b, _f = agent._global_resched(
        plan, _picked(), [_slb()], rain_days=RAIN, max_evals=0
    )

    assert moves == []
    assert plan.model_dump() == before


def test_lns_destroy_repair_resequences_big_into_morning():
    """单点 move/swap 无货可挪时，拆日重建把 240 分钟大点重排进上午
    （就地重排分支——治用户旧案「华清池 13:00 起排、上午空」形状）。"""
    agent = PlanningAgent(_NoLLM())
    lunch = VisitItem(
        item_id="lunch-1",
        name="午饭（自由安排）",
        category="food",
        city="西安",
        day=1,
        start_time=time(12, 0),
        end_time=time(13, 0),
        duration_minutes=60,
        pinned=True,
        soft_pin=True,
    )
    big = VisitItem(
        item_id="big",
        name="华清池",
        city="西安",
        day=1,
        duration_minutes=240,
        start_time=time(13, 0),
        end_time=time(17, 0),
    )
    day1 = DayPlan(day=1, base_city="西安", items=[lunch, big])
    day2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            VisitItem(
                item_id="p",
                name="钉点",
                city="西安",
                day=2,
                duration_minutes=90,
                start_time=time(9, 0),
                end_time=time(10, 30),
                pinned=True,
            )
        ],
    )
    plan = ItineraryPlan(itinerary_id="it1", cities=["西安"], days=[day1, day2])

    moves, b, f = agent._global_resched(plan, [], [])

    assert moves and "就地重排" in moves[0]
    big_it = next(
        i
        for d in plan.days
        for i in d.items
        if isinstance(i, VisitItem) and i.item_id == "big"
    )
    assert big_it.start_time == time(9, 0)
    assert f > b


def test_lns_disclosure_moves_are_strings():
    """移动摘要可读（供假设区披露）——冒烟断言的形状守卫。"""
    agent = PlanningAgent(_NoLLM())
    plan = _xian_fixture()
    moves, _b, _f = agent._global_resched(plan, _picked(), [_slb()], rain_days=RAIN)
    assert all(isinstance(m, str) and m for m in moves)
    assert any("→第" in m or "对调" in m or "重排" in m for m in moves)


def test_lns_insertion_evaluator_fills_anchor_gap():
    """v1.5：240 分钟未排条目夹在两个全钉锚之间——兜底法因 ±30 缓冲
    判死（10:30+240 撞 B 的 13:30 缓冲；B 后 16:30 又超入场闸），插入式
    求解按锚背靠背落 10:00-14:00——评估器升级解锁这类移动。"""
    agent = PlanningAgent(_NoLLM())
    a = VisitItem(
        item_id="pa",
        name="锚A",
        city="西安",
        day=1,
        duration_minutes=60,
        start_time=time(9, 0),
        end_time=time(10, 0),
        pinned=True,
    )
    b = VisitItem(
        item_id="pb",
        name="锚B",
        city="西安",
        day=1,
        duration_minutes=120,
        start_time=time(14, 0),
        end_time=time(16, 0),
        pinned=True,
    )
    x = VisitItem(
        item_id="vx",
        name="大点X",
        city="西安",
        day=1,
        duration_minutes=240,
    )
    day1 = DayPlan(day=1, base_city="西安", items=[a, b, x])
    day2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            VisitItem(
                item_id="pc",
                name="堵日C",
                city="西安",
                day=2,
                duration_minutes=660,
                start_time=time(9, 0),
                end_time=time(20, 0),
                pinned=True,
            )
        ],
    )
    plan = ItineraryPlan(itinerary_id="it1", cities=["西安"], days=[day1, day2])

    moves, b_total, f_total = agent._global_resched(plan, [], [])

    assert moves, "插入式评估应解锁拆日重建"
    assert f_total > b_total
    x_it = next(
        i
        for d in plan.days
        for i in d.items
        if isinstance(i, VisitItem) and i.item_id == "vx"
    )
    assert x_it.start_time == time(10, 0)  # 锚背靠背：10:00-14:00
    assert x_it.end_time == time(14, 0)


def test_lns_shake_bounded_never_worse():
    """S2.3：全信号无改进移动时 shake 触发（≤2 次、SA 接受劣化继续
    搜），收工取历史最优快照——扰动路径绝不把结果变差（此处=恒等）。"""
    agent = PlanningAgent(_NoLLM())
    a = VisitItem(
        item_id="pa",
        name="锚A",
        city="西安",
        day=1,
        duration_minutes=60,
        start_time=time(9, 0),
        end_time=time(10, 0),
        pinned=True,
    )
    b = VisitItem(
        item_id="pb",
        name="锚B",
        city="西安",
        day=1,
        duration_minutes=120,
        start_time=time(14, 0),
        end_time=time(16, 0),
        pinned=True,
    )
    x = VisitItem(
        item_id="vx",
        name="巨点X",
        city="西安",
        day=1,
        duration_minutes=480,  # 任何空档都装不下：全渠道无解
    )
    day1 = DayPlan(day=1, base_city="西安", items=[a, b, x])
    day2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            VisitItem(
                item_id="pc",
                name="堵日C",
                city="西安",
                day=2,
                duration_minutes=300,
                start_time=time(9, 0),
                end_time=time(14, 0),
                pinned=True,
            )
        ],
    )
    plan = ItineraryPlan(itinerary_id="it1", cities=["西安"], days=[day1, day2])
    before = plan.model_dump()

    moves, b_total, f_total = agent._global_resched(plan, [], [])

    assert moves == []  # 历史最优=基线：不产出劣化披露
    assert f_total == b_total
    assert plan.model_dump() == before  # 恒等：扰动绝不落地劣化
