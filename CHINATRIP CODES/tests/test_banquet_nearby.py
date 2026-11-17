"""宴秀就近规则回归锚（2026-11-13 用户拍板）.

用户原话：「红鼎宴 should be picked up nearby unless there is special
reason」——成都 Day 2 主景点是环球中心，红鼎宴就在同址（<1km），却因
构造期餐卡轮转被发到失重餐厅日、终装每场闸再按簇跟随挪回 Day 2 时
只能清掉时刻，最终出现「蜀宴赋占 18:30、红鼎宴无时刻」的倒挂。

本锚覆盖两道新规则：
1. `_reassign_banquet_days`：宴秀按「当日非餐景点簇」就近择日，且
   每宴一日（宴日不叠第二宴）；普通餐卡不动。
2. `_meal_slot_plan`：同日多张宴秀卡争晚餐槽时，距当日景点簇最近者
   得晚餐（不再按 picked 顺序先到先得）。
"""

from app.services.agent.plan import _meal_slot_plan, _reassign_banquet_days

# 环球中心（Day 2 主景点）与红鼎宴同址；蜀宴赋在东郊记忆（远）。
_GLOBAL_CENTER = {"lon": 104.063426, "lat": 30.568779}
_HONGDING = {"lon": 104.070327, "lat": 30.574887}
_SHUYAN = {"lon": 104.122934, "lat": 30.667529}
_PEOPLE_PARK = {"lon": 104.057676, "lat": 30.657099}
_MAWANGZI = {"lon": 104.083999, "lat": 30.651237}


def _sight(name: str, day: int, location: dict) -> dict:
    return {
        "name": name,
        "category": "attraction",
        "city": "成都",
        "day": day,
        "location": location,
        "duration_minutes": 120,
    }


def _food(name: str, day: int, location: dict, hours: str = "") -> dict:
    return {
        "name": name,
        "category": "food",
        "city": "成都",
        "day": day,
        "location": location,
        "duration_minutes": 60,
        "opening_hours": hours,
    }


def _cands() -> dict[str, dict]:
    return {
        "红鼎宴": {
            "name": "红鼎宴",
            "source_poi_id": "curated:成都:红鼎宴",
            "category": "food",
            "location": _HONGDING,
            "opening_hours": "午宴12:30-14:10；晚宴18:20-20:10",
        },
        "蜀宴赋": {
            "name": "蜀宴赋",
            "source_poi_id": "curated:成都:蜀宴赋",
            "category": "food",
            "location": _SHUYAN,
            "opening_hours": "周一至周日 10:00-22:00",
        },
        "马旺子": {
            "name": "马旺子",
            "source_poi_id": "curated:成都:马旺子",
            "category": "food",
            "location": _MAWANGZI,
            "opening_hours": "周一至周日 11:00-21:00",
        },
        "失重餐厅": {
            "name": "失重餐厅",
            "source_poi_id": "curated:成都:失重餐厅",
            "category": "food",
            "location": _GLOBAL_CENTER,
            "opening_hours": "周一至周日 10:00-22:00",
        },
        "龙抄手": {
            "name": "龙抄手",
            "source_poi_id": "curated:成都:龙抄手",
            "category": "food",
            "location": _MAWANGZI,
            "opening_hours": "周一至周日 08:00-21:00",
        },
    }


def test_banquet_day_moves_to_nearby_cluster():
    """红鼎宴在构造期被轮转到 Day 1，按环球中心就近改回 Day 2。

    普通餐卡（失重餐厅）保持原日——近距规则只收宴秀，不扰动到达日
    的普通餐布局。
    """
    picked = [
        _sight("人民公园", 2, _PEOPLE_PARK),
        _sight("成都环球中心", 2, _GLOBAL_CENTER),
        _sight("成都大熊猫繁育研究基地", 3, {"lon": 104.147, "lat": 30.733}),
        _food("红鼎宴", 1, _HONGDING),
        _food("失重餐厅", 1, _GLOBAL_CENTER),
    ]

    moved = _reassign_banquet_days(picked, _cands(), {"成都": (1, 4)})

    assert moved == ["红鼎宴"]
    assert picked[3]["day"] == 2  # 红鼎宴跟环球中心簇
    assert picked[4]["day"] == 1  # 普通餐卡不动


def test_one_banquet_per_day_nearest_wins_day():
    """两宴都指向 Day 2 时，近者（红鼎宴）取 Day 2，远者让到次近天。"""
    picked = [
        _sight("人民公园", 2, _PEOPLE_PARK),
        _sight("成都环球中心", 2, _GLOBAL_CENTER),
        _sight("成都大熊猫繁育研究基地", 3, {"lon": 104.147, "lat": 30.733}),
        _food("蜀宴赋", 1, _SHUYAN),
        _food("红鼎宴", 1, _HONGDING),
    ]

    _reassign_banquet_days(picked, _cands(), {"成都": (1, 4)})

    assert picked[4]["day"] == 2  # 红鼎宴 0.8km 贴环球中心
    assert picked[3]["day"] != 2  # 蜀宴赋不叠同一宴日


def test_nearest_banquet_gets_dinner_not_first_in_order():
    """同日两宴：远者先入 picked 也不得抢走近者的晚餐槽。"""
    picked = [
        _sight("成都环球中心", 2, _GLOBAL_CENTER),
        _food("蜀宴赋", 2, _SHUYAN),
        _food("红鼎宴", 2, _HONGDING),
        _food("马旺子", 2, _MAWANGZI),
    ]

    slots = _meal_slot_plan(picked, _cands())

    assert slots.get(id(picked[2])) == "dinner"  # 红鼎宴贴簇
    assert slots.get(id(picked[3])) == "lunch"  # 普通餐落午餐
    assert id(picked[1]) not in slots  # 蜀宴赋无槽（下游转备选）


def test_ordinary_foods_keep_lunch_then_dinner_order():
    """普通餐卡行为不变：首张午餐、次张晚餐、第三张无槽。"""
    picked = [
        _sight("成都环球中心", 2, _GLOBAL_CENTER),
        _food("马旺子", 2, _MAWANGZI),
        _food("失重餐厅", 2, _GLOBAL_CENTER),
        _food("龙抄手", 2, _MAWANGZI),
    ]

    slots = _meal_slot_plan(picked, _cands())

    assert slots.get(id(picked[1])) == "lunch"
    assert slots.get(id(picked[2])) == "dinner"
    assert id(picked[3]) not in slots


def test_no_sight_coords_keeps_existing_days():
    """无已落景点坐标：宴秀日不动（宁缺勿猜）。"""
    picked = [_food("红鼎宴", 1, _HONGDING)]
    moved = _reassign_banquet_days(picked, _cands(), {"成都": (1, 4)})
    assert moved == []
    assert picked[0]["day"] == 1
