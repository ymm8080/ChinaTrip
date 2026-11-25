# -*- coding: utf-8 -*-
"""R38（2026-11-25 用户「北京璞瑄酒店·大堂吧既不是娱乐也不是酒店也不是
餐厅 / 当作餐厅为什么后面还有一个晚餐自由卡」）。

大堂吧 / 酒廊 / 酒吧不是正餐餐厅。R29 把 restaurants 表每一行都投影成
category="food"，导致这类行靠 TA 满分挤进 geo 餐池、顶掉真餐馆，当天
晚餐又落回「晚饭（自由安排）」占位。本测试锁住：

1. is_non_meal_venue 按菜系组 + 名称标记判定（大堂吧/lounge/酒吧）；
2. select_geo_rated 先于评分闸剔除——满分大堂吧不进池，真餐馆补位；
3. 同名普通餐馆不误伤；缺字段的行不报错不误伤；
4. 原行留库、top_pois 老路径语义零影响（本模块只过滤 geo 候选）。
"""

from __future__ import annotations

from app.services.meal_geo import is_non_meal_venue, select_geo_rated


def _row(name, lon, lat, rating, count=None, **kw):
    row = {
        "name": name,
        "category": "food",
        "location": (lon, lat),
        "rating": rating,
        "rating_count": count,
        "source_poi_id": name,
    }
    row.update(kw)
    return row


# ------------------------------------------------------- 非正餐判定（纯函数）


def test_lounge_name_marked_non_meal():
    assert is_non_meal_venue(_row("北京璞瑄酒店·大堂吧", 116.4, 39.9, 5.0))
    assert is_non_meal_venue(
        _row("北京王府半岛酒店·屋顶酒吧 Yun Summer Lounge", 116.4, 39.9, 4.8)
    )
    assert is_non_meal_venue(_row("XX Hotel Lobby Lounge", 116.4, 39.9, 4.9))
    assert is_non_meal_venue(_row("左岸酒廊", 116.4, 39.9, 4.7))


def test_bar_cuisine_group_marked_non_meal_even_without_name_marker():
    # 菜系组命中即非正餐（名称无「吧/酒廊」字样——真餐馆名也可能含这些字）
    assert is_non_meal_venue(
        _row("某店", 116.4, 39.9, 5.0, cuisine_group="酒吧夜店", cuisine="酒")
    )


def test_real_restaurant_not_marked():
    assert not is_non_meal_venue(_row("南门涮肉(东单店)", 116.4, 39.9, 4.8))
    assert not is_non_meal_venue(
        _row(
            "四季民福烤鸭店",
            116.4,
            39.9,
            4.9,
            cuisine_group="北方风味",
            cuisine="烤鸭",
        )
    )
    assert not is_non_meal_venue(_row("叶叶菩提(旗舰店)", 116.4, 39.9, 5.0))


def test_restaurant_with_lounge_in_name_not_marked():
    """库审（2026-11-25）：名字里带「餐厅」的是真馆子——「Calypso地中海餐
    厅·酒廊」菜系组西餐，只因含「酒廊」被剔会白让掉一家正经餐厅。"""
    assert not is_non_meal_venue(
        _row(
            "上海静安香格里拉大酒店·Calypso地中海餐厅·酒廊",
            121.45,
            31.23,
            4.7,
            cuisine_group="西餐",
        )
    )
    assert not is_non_meal_venue(
        _row("The Georg Restaurant & Bar", 116.4, 39.9, 4.6)
    )


def test_empty_or_missing_fields_no_false_positive():
    assert not is_non_meal_venue({})
    assert not is_non_meal_venue({"name": "", "cuisine_group": None})


# ------------------------------------------- select_geo_rated 真餐馆补位（R38）


def test_lounge_dropped_before_rating_gate_real_restaurant_takes_slot():
    """复刻 2155da21 Day3：满分大堂吧 + 4.5/4.9 真餐馆同锚点。

    改前大堂吧以 5.0 独占 per_anchor=1，真餐馆落选 → 当天晚餐落「晚饭」
    自由卡；改后大堂吧被剔，真餐馆补位，仍只有一家进池（行为稳定）。
    """
    rows = [
        _row("北京璞瑄酒店·大堂吧", 116.4161, 39.9248, 5.0, 37),
        _row("南门涮肉(东单店)", 116.4279, 39.9088, 4.5, 106),
        _row("四季民福烤鸭店(王府井店)", 116.4100, 39.9150, 4.9, 500),
    ]
    picked = select_geo_rated(rows, [(116.4100, 39.9150)], per_anchor=1, limit=4)
    names = [r["name"] for r in picked]
    assert "北京璞瑄酒店·大堂吧" not in names
    assert names == ["四季民福烤鸭店(王府井店)"]


def test_lounge_only_pool_returns_empty():
    rows = [
        _row("北京璞瑄酒店·大堂吧", 116.4161, 39.9248, 5.0, 37),
        _row("某酒店·酒廊", 116.4170, 39.9250, 4.9, 60),
    ]
    assert select_geo_rated(rows, [(116.4100, 39.9150)]) == []


def test_geo_pool_keeps_old_path_for_empty_cuisine_real_shop():
    # 无菜系键的真餐馆仍可被 geo 池选中（R29 原行为不变）
    rows = [_row("无名小店", 116.4000, 39.9100, 4.1, 20)]
    assert [r["name"] for r in select_geo_rated(rows, [(116.4000, 39.9100)])] == [
        "无名小店"
    ]
