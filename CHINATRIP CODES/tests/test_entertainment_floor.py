# -*- coding: utf-8 -*-
"""每行程宜有一场娱乐（2026-11-03 用户拍板 every itinerary should
include one entertainment，同日二次更正：nice-to-have 非强制、口径=
每行程一次判定非按城/按日）。

两层软实现（无强制注入）：
① 4/日裁并闸——已选演出在满员日（当天已 4 个白天点）不被裁掉
   （演出=S5 晚间收尾事件不占白天游览窗，纯档位核算）；
② 评分器 no_entertainment 软罚——整程零演出进指标面板/LNS（每行程
   一次判定；纯交通/占位形态不罚）。
"""

from datetime import time

from app.services.agent.plan import PlanningAgent
from app.services.itinerary.models import DayPlan, ItineraryPlan, VisitItem
from app.services.itinerary.scoring import plan_score


def _sight_spec(name, day, *, city="西安"):
    return {
        "name": name,
        "city": city,
        "category": "sight",
        "day": day,
        "duration_minutes": 90,
        "location": {"lon": 108.95, "lat": 34.27},
    }


def _show_spec(name, day, *, city="西安"):
    return {
        "name": name,
        "city": city,
        "category": "entertainment",
        "day": day,
        "duration_minutes": 80,
        "location": {"lon": 109.0, "lat": 34.3},
        "best_visit_time": "show",
    }


# --- ① 4/日裁并闸豁免 ------------------------------------------------------


def test_cap_gate_keeps_show_on_full_day():
    # 确定性路径形态：day2 已 4 个白天点 + 钉场夜演（spec 殿后）。
    # 旧版把 entertainment 计入 4/日闸 → 满员日裁掉夜场 → 整程零演出。
    picked = [_sight_spec(f"点{i}", 2) for i in range(4)]
    picked += [_show_spec("《长恨歌》", 2)]
    kept, dropped = PlanningAgent._cap_sights_per_day(picked)
    assert [p["name"] for p in kept if p["category"] == "entertainment"] == [
        "《长恨歌》"
    ]
    assert dropped == []  # 4 个白天点全保留，演出不占闸
    # 真超载（第 5 个白天点）照裁
    picked2 = picked + [_sight_spec("点5", 2)]
    kept2, dropped2 = PlanningAgent._cap_sights_per_day(picked2)
    assert "点5" not in [p["name"] for p in kept2]
    assert dropped2 == [("第2天 点5", "day 2 点5")]


# --- ② 评分器零娱乐软罚（每行程一次判定） -----------------------------------


def _plan(items, days=1):
    by_day = items if isinstance(items, dict) else {1: items}
    return ItineraryPlan(
        itinerary_id="t",
        cities=["西安"],
        days=[
            DayPlan(day=d + 1, base_city="西安", items=by_day.get(d + 1, []))
            for d in range(days)
        ],
    )


def _visit(item_id, *, cat="sight", dur=90, start=None, end=None, day=1, **kw):
    return VisitItem(
        item_id=item_id,
        name=item_id,
        city="西安",
        day=day,
        category=cat,
        duration_minutes=dur,
        start_time=start,
        end_time=end,
        **kw,
    )


def test_no_entertainment_penalized_when_sights_exist():
    plan = _plan(
        [
            _visit("a", start=time(9, 0), end=time(10, 30)),
            _visit("b", start=time(14, 0), end=time(15, 30)),
        ]
    )
    sc = plan_score(plan)
    assert sc.soft["no_entertainment"] == -40
    assert sc.counts["entertainment"] == 0
    assert sc.total == -40


def test_entertainment_present_clears_penalty():
    plan = _plan(
        [
            _visit("a", start=time(9, 0), end=time(10, 30)),
            _visit(
                "s",
                cat="entertainment",
                dur=80,
                start=time(19, 30),
                end=time(20, 50),
                best_visit_time="show",
            ),
        ]
    )
    sc = plan_score(plan)
    assert sc.soft["no_entertainment"] == 0
    assert sc.counts["entertainment"] == 1
    assert sc.total == 0


def test_one_show_covers_whole_trip_not_per_day():
    # 口径=每行程一次判定（2026-11-03 更正 not for each day）：第 1 天
    # 有演出、第 2 天纯游览 → 整程已含娱乐，不罚（无需每天一场）。
    plan = _plan(
        {
            1: [
                _visit("a", start=time(9, 0), end=time(10, 30)),
                _visit(
                    "s",
                    cat="entertainment",
                    dur=80,
                    start=time(19, 30),
                    end=time(20, 50),
                    best_visit_time="show",
                ),
            ],
            2: [_visit("b", day=2, start=time(9, 0), end=time(10, 30))],
        },
        days=2,
    )
    sc = plan_score(plan)
    assert sc.counts["entertainment"] == 1
    assert sc.soft["no_entertainment"] == 0


def test_day_show_counts_as_entertainment():
    # 多场次白天演出：category=sight 但 best_visit_time=show —— 与
    # solver._is_show 同口径，计入娱乐清罚。
    plan = _plan(
        [
            _visit("a", start=time(9, 0), end=time(10, 30)),
            _visit("d", start=time(14, 0), end=time(15, 20), best_visit_time="show"),
        ]
    )
    sc = plan_score(plan)
    assert sc.counts["entertainment"] == 1
    assert sc.soft["no_entertainment"] == 0


def test_meal_only_plan_not_penalized():
    # 纯餐/酒店形态（无游览点）：不罚——罚的是「该有而没排」。
    plan = _plan(
        [_visit("lunch", cat="food", dur=60, start=time(12, 0), end=time(13, 0))]
    )
    sc = plan_score(plan)
    assert sc.soft["no_entertainment"] == 0
