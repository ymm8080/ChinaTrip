# -*- coding: utf-8 -*-
"""S3 指标回归（坏例库 v1）：锁定 2026-11-01 用户实际遇到的坏行程形状。

坏例=旧构建产物（session 4f228cfb 摘录）：第3天上午空白 + 《秦俑情》
未排 + 雨天露天华清池。分值语义若漂移（权重/口径改动）此处报警——
改权重必须显式更新本文件并在提交信息里说明依据。
"""

from app.services.itinerary.scoring import score_payload

RAIN = {"西安": {3, 4}}

# 摘自 h5_state.db plan_sessions 4f228cfb（day3/day4，字段从简）
BAD_PLAN = {
    "itinerary_id": "it-4f228cfb-excerpt",
    "cities": ["上海", "西安", "上海"],
    "days": [
        {
            "day": 3,
            "base_city": "西安",
            "items": [
                {
                    "item_id": "food-d3-lunch-1",
                    "name": "福顺祥大盘鸡(临潼店)",
                    "category": "food",
                    "city": "西安",
                    "day": 3,
                    "start_time": "12:00:00",
                    "end_time": "13:00:00",
                    "duration_minutes": 60,
                    "pinned": True,
                    "soft_pin": False,
                },
                {
                    "item_id": "v15",
                    "name": "临潼区华清池景区",
                    "category": "attraction",
                    "city": "西安",
                    "day": 3,
                    "start_time": "13:00:00",
                    "end_time": "17:00:00",
                    "duration_minutes": 240,
                    "rain_ok": "no",
                },
                {
                    "item_id": "v16",
                    "name": "《秦俑情》",
                    "category": "entertainment",
                    "city": "西安",
                    "day": 3,
                    "start_time": None,
                    "end_time": None,
                    "duration_minutes": 80,
                    "rain_ok": "yes",
                    "best_visit_time": "show",
                },
            ],
        },
        {
            "day": 4,
            "base_city": "西安",
            "items": [
                {
                    "item_id": "v17",
                    "name": "秦始皇兵马俑博物馆",
                    "category": "attraction",
                    "city": "西安",
                    "day": 4,
                    "start_time": "09:00:00",
                    "end_time": "10:30:00",
                    "duration_minutes": 90,
                    "rain_ok": "yes",
                },
                {
                    "item_id": "v18",
                    "name": "钟楼",
                    "category": "sight",
                    "city": "西安",
                    "day": 4,
                    "start_time": "11:00:00",
                    "end_time": "12:00:00",
                    "duration_minutes": 60,
                    "rain_ok": "yes",
                },
                {
                    "item_id": "food-d4-lunch-1",
                    "name": "海底捞火锅(博乐里店)",
                    "category": "food",
                    "city": "西安",
                    "day": 4,
                    "start_time": "12:00:00",
                    "end_time": "13:00:00",
                    "duration_minutes": 60,
                    "pinned": True,
                    "soft_pin": False,
                },
                {
                    "item_id": "v20",
                    "name": "《梦回大唐》",
                    "category": "entertainment",
                    "city": "西安",
                    "day": 4,
                    "start_time": "17:30:00",
                    "end_time": "18:50:00",
                    "duration_minutes": 80,
                    "rain_ok": "yes",
                    "best_visit_time": "show",
                },
            ],
        },
    ],
}

# 同案修复形态（晨间借调/LNS 应达成的目标布局）：华清池顶上午、
# 午餐顺延 13:00、秦俑情落 14:00 场次
REPAIRED_PLAN = {
    "itinerary_id": "it-4f228cfb-repaired",
    "cities": ["上海", "西安", "上海"],
    "days": [
        {
            "day": 3,
            "base_city": "西安",
            "items": [
                {
                    "item_id": "v15",
                    "name": "临潼区华清池景区",
                    "category": "attraction",
                    "city": "西安",
                    "day": 3,
                    "start_time": "09:00:00",
                    "end_time": "13:00:00",
                    "duration_minutes": 240,
                    "rain_ok": "no",
                },
                {
                    "item_id": "food-d3-lunch-1",
                    "name": "福顺祥大盘鸡(临潼店)",
                    "category": "food",
                    "city": "西安",
                    "day": 3,
                    "start_time": "13:00:00",
                    "end_time": "14:00:00",
                    "duration_minutes": 60,
                    "pinned": True,
                    "soft_pin": True,
                },
                {
                    "item_id": "v16",
                    "name": "《秦俑情》",
                    "category": "entertainment",
                    "city": "西安",
                    "day": 3,
                    "start_time": "14:00:00",
                    "end_time": "15:20:00",
                    "duration_minutes": 80,
                    "rain_ok": "yes",
                    "best_visit_time": "show",
                },
            ],
        },
        BAD_PLAN["days"][1],
    ],
}


def test_bad_case_4f228cfb_scores_hard_penalties():
    """用户实际坏例：untimed -100 + 空白上午 -80 + 雨露天 -15 = -195。"""
    sc = score_payload(BAD_PLAN, rain_days=RAIN)
    assert sc.hard["untimed"] == -100
    assert sc.hard["blank_morning"] == -80
    assert sc.soft["rain_exposed"] == -15
    assert sc.total == -195
    assert sc.counts["untimed"] == 1
    assert sc.counts["blank_morning"] == 1


def test_repaired_case_has_zero_hard_penalties():
    """修复形态：硬惩罚全零（剩雨露天 -15 + 午餐漂移 -3 = -18）。
    这就是晨间借调 / LNS 应把坏例推进到的目标分。"""
    sc = score_payload(REPAIRED_PLAN, rain_days=RAIN)
    assert sc.ok
    assert sc.hard == {"untimed": 0, "blank_morning": 0, "violations": 0}
    assert sc.soft["rain_exposed"] == -15
    assert sc.soft["lunch_drift"] == -3
    assert sc.total == -18
