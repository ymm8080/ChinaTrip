# -*- coding: utf-8 -*-
"""每行程至少一场娱乐（2026-11-03 用户拍板 every itinerary should
include one entertainment）。

三层锁：
① 4/日裁并闸——确定性路径按城钉的夜场在满员日（当天已 4 个白天点）
   不再被裁掉（演出=S5 晚间收尾事件不占白天游览窗）；
② _ensure_entertainment 兜底——LLM/占位/裁并路径整程零演出时按城补
   钉最优夜场（返程日让位前一天、已满足城市不动、无供应点名披露）；
③ 评分器 no_entertainment 软罚——「该有而没排」形态进指标面板/LNS
   （纯交通/占位形态不罚）。
"""

from datetime import time

from app.services.agent.plan import PlanningAgent
from app.services.itinerary.models import DayPlan, ItineraryPlan, VisitItem
from app.services.itinerary.scoring import plan_score


def _night_show_cand(name, *, city="西安", tier5a=False):
    c = {
        "name": name,
        "city": city,
        "category": "entertainment",
        "best_visit_time": "show",
        "opening_hours": "19:30-21:00",
        "location": {"lon": 109.0, "lat": 34.3},
        "suggested_duration_min": 80,
    }
    if tier5a:
        c["tags"] = ["5a"]
    return c


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


# --- ② _ensure_entertainment 兜底 ------------------------------------------


def test_floor_injects_best_night_show_at_city_last_day():
    picked = [_sight_spec("兵马俑", 1), _sight_spec("钟楼", 2)]
    cands = [
        _night_show_cand("《秦俑情》"),
        _night_show_cand("《长恨歌》", tier5a=True),  # tier 更优 → 选它
    ]
    new_picked, notes = PlanningAgent._ensure_entertainment(
        picked, cands, 2, {"西安": (1, 2)}
    )
    shows = [s for s in new_picked if s["category"] == "entertainment"]
    assert len(shows) == 1
    assert shows[0]["name"] == "《长恨歌》"  # 池序=完整优先级梯子
    assert shows[0]["day"] == 2  # 城市窗口末日收尾
    assert shows[0]["duration_minutes"] == 80
    assert any("已补排演出" in zh and "《长恨歌》" in zh for zh, _ in notes)


def test_floor_shifts_off_return_day():
    # 2 城行程末段：hi=2=days 且是返程日 → 夜场让位前一天（同确定性
    # 路径 2026-10-31 沪-西安-沪拍板口径）。
    picked = [_sight_spec("外滩", 1)]
    cands = [_night_show_cand("《长恨歌》", city="上海")]
    new_picked, _ = PlanningAgent._ensure_entertainment(
        picked, cands, 2, {"上海": (1, 2)}, transfer_days={2}
    )
    shows = [s for s in new_picked if s["category"] == "entertainment"]
    assert len(shows) == 1 and shows[0]["day"] == 1


def test_floor_respects_city_with_existing_show():
    # 已排演出（含多场次白天演出 category=sight/bvt=show，按名对候选）
    # 的城市不重复注入。
    day_show_cand = {
        "name": "《秦俑情》",
        "city": "西安",
        "category": "sight",
        "best_visit_time": "show",
        "opening_hours": "多场 11:00/14:00",
        "location": {"lon": 109.0, "lat": 34.3},
        "suggested_duration_min": 80,
    }
    picked = [
        _sight_spec("兵马俑", 1),
        {  # spec 层 category 是 sight，靠名字对上演出候选
            "name": "《秦俑情》",
            "city": "西安",
            "category": "sight",
            "day": 1,
            "duration_minutes": 80,
        },
    ]
    cands = [day_show_cand, _night_show_cand("《长恨歌》")]
    new_picked, notes = PlanningAgent._ensure_entertainment(
        picked, cands, 1, {"西安": (1, 1)}
    )
    assert len(new_picked) == 2  # 未注入
    assert notes == []


def test_floor_discloses_when_no_show_supply():
    picked = [_sight_spec("兵马俑", 1)]
    new_picked, notes = PlanningAgent._ensure_entertainment(
        picked, [_sight_spec("钟楼", 1)], 1, {"西安": (1, 1)}
    )
    assert len(new_picked) == 1  # 无供应不硬造
    assert any("暂无演出/娱乐类" in zh for zh, _ in notes)


def test_floor_skips_show_candidates_without_location():
    # 演出行缺坐标（坐标闸口径）：不可排 → 按无供应披露，不注入。
    locless = _night_show_cand("《梦回大唐》")
    locless["location"] = None
    picked = [_sight_spec("兵马俑", 1)]
    new_picked, notes = PlanningAgent._ensure_entertainment(
        picked, [locless], 1, {"西安": (1, 1)}
    )
    assert len(new_picked) == 1
    assert any("暂无演出/娱乐类" in zh for zh, _ in notes)


# --- ③ 评分器零娱乐软罚 ----------------------------------------------------


def _plan(items):
    return ItineraryPlan(
        itinerary_id="t",
        cities=["西安"],
        days=[DayPlan(day=1, base_city="西安", items=items)],
    )


def _visit(item_id, *, cat="sight", dur=90, start=None, end=None, **kw):
    return VisitItem(
        item_id=item_id,
        name=item_id,
        city="西安",
        day=1,
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
