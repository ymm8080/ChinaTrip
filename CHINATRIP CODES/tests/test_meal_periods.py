"""meal_periods 餐段推导单测（DESIGN user_tag_two_level_2026-11-10 §三）。

覆盖：真实回源营业时间格式解析、六枚举规则与边界时刻、菜系闸、
空输入不猜、_allowed_slots_for 显式优先切换。
"""

from app.services.meal_periods import (
    infer_meal_periods,
    parse_opening_windows,
)
from app.services.restaurants import _allowed_slots_for, candidate_from_poi_dict

# --- 解析：库内回源真实格式（采样自 pois/amap/baidu/ctrip 链） -------------


def test_parse_plain_and_weekday_prefix():
    assert parse_opening_windows("10:00-22:00") == [(600, 1320)]
    assert parse_opening_windows("周一至周日 10:00-22:00") == [(600, 1320)]
    assert parse_opening_windows("周二至周日 09:00-17:00") == [(540, 1020)]
    assert parse_opening_windows("每周一至周五 09:00-17:00") == [(540, 1020)]


def test_parse_multi_window_and_annotations():
    assert parse_opening_windows("10:00-14:00,17:00-21:00") == [
        (600, 840),
        (1020, 1260),
    ]
    assert parse_opening_windows("10:30-14:00, 16:30-21:00") == [
        (630, 840),
        (990, 1260),
    ]
    # 中文分号分段 + 括号注释剥掉
    assert parse_opening_windows("11:00-14:00；17:00-21:30（汉文化主题演艺+唐风换装）") == [
        (660, 840),
        (1020, 1290),
    ]
    assert parse_opening_windows("今天08:30-17:00开放（16:30停止入园）") == [(510, 1020)]


def test_parse_cross_midnight_and_all_day():
    # 跨零点 +24h 归一
    assert parse_opening_windows("17:00-02:00") == [(1020, 1560)]
    assert parse_opening_windows("09:00-07:00") == [(540, 1860)]
    # 全天 24:00 收口
    assert parse_opening_windows("00:00-24:00") == [(0, 1440)]
    assert parse_opening_windows("周一至周日 00:00-24:00") == [(0, 1440)]
    assert parse_opening_windows("全年全天开放") == [(0, 1440)]
    assert parse_opening_windows("24小时营业") == [(0, 1440)]


def test_parse_noise_tails_are_stripped():
    assert parse_opening_windows("周二至周日 09:00-17:00,节假日以官方通知为准") == [
        (540, 1020)
    ]
    assert parse_opening_windows("周一至周日 09:00-17:00 最晚进入16:30") == [(540, 1020)]
    assert parse_opening_windows("今天08:00-18:00开放") == [(480, 1080)]
    assert parse_opening_windows("周一至周日 00:00-24:00；具体营业状态以当天开放情况为准") == [
        (0, 1440)
    ]
    # 休息日注记剥掉不致失败（meal_periods 无日粒度，取开放日窗口）
    assert parse_opening_windows("周一 全天关闭；周二至周日 09:00-17:00 最晚进入16:30") == [
        (540, 1020)
    ]


def test_parse_unparsable_returns_empty_not_guess():
    """散文/场次文案/残缺格式一律 []，绝不从散文里猜窗口。"""
    for bad in (
        None,
        "",
        "   ",
        "仅夜场（约19:30，周末加21:00航次，周一休）",
        "90分钟剧情式餐秀（预订制，2025-10开业）",
        "午宴12:30-14:10；晚宴18:20-20:10",
        "正餐午晚市；闽南特色演出每晚18:30-20:30（歌仔戏等）",
        "精华游:日游11:00-17:45，夜游18:00-21:00（具体班次以现场换票为准）",
        "多场（约14:00/16:30/19:30，以当日公告为准）",
        "节假日以官方通知为准",
        "周一 全天关闭",
        "10:00-25:00",  # 小时越界
        "10:00-10:00",  # 零长窗口
        "abc-def",
    ):
        assert parse_opening_windows(bad) == [], bad


# --- 六枚举规则与边界 ------------------------------------------------------


def test_standard_full_day_restaurant():
    """10:00-22:00 标准店：午+晚，无早/夜宵。"""
    assert infer_meal_periods("10:00-22:00", None) == ["lunch", "dinner"]


def test_breakfast_open_boundary():
    """开门 ≤09:00 算早餐，09:01 不算。"""
    assert "breakfast" in infer_meal_periods("09:00-22:00", None)
    assert "breakfast" not in infer_meal_periods("09:01-22:00", None)
    assert infer_meal_periods("09:00-22:00", None) == ["breakfast", "lunch", "dinner"]


def test_lunch_overlap_boundary():
    """与 11:00–14:00 有正长交集才算午市。"""
    assert "lunch" in infer_meal_periods("11:00-14:00", None)
    assert "lunch" in infer_meal_periods("11:30-14:30", None)  # 典型午市店
    assert "lunch" not in infer_meal_periods("08:00-11:00", None)  # 11:00 整点收
    assert "lunch" in infer_meal_periods("08:00-11:01", None)
    assert "lunch" not in infer_meal_periods("14:01-21:00", None)


def test_dinner_overlap_boundary():
    assert "dinner" in infer_meal_periods("17:00-21:00", None)
    assert "dinner" in infer_meal_periods("16:30-21:30", None)
    assert "dinner" not in infer_meal_periods("08:00-17:00", None)
    assert "dinner" in infer_meal_periods("08:00-17:01", None)
    assert "dinner" not in infer_meal_periods("21:01-23:00", None)


def test_late_night_close_24_and_cross_0200():
    assert "late_night" in infer_meal_periods("19:00-24:00", None)
    assert "late_night" not in infer_meal_periods("19:00-23:59", None)
    # 跨零点（关门 ≥24:00 归一后必中）
    assert "late_night" in infer_meal_periods("23:00-01:00", None)
    assert "late_night" in infer_meal_periods("17:00-02:00", None)
    # 凌晨窗口覆盖 02:00（∩02:00）
    assert "late_night" in infer_meal_periods("00:30-04:00", None)
    assert "late_night" not in infer_meal_periods("00:00-01:00", None)


def test_early_tea_cantonese_only_and_strict_1030():
    """early_tea 双闸：粤式茶点 ∧ 开门 <10:30（不含）。"""
    assert infer_meal_periods("10:00-14:00", "粤式茶点") == ["early_tea", "lunch"]
    assert "early_tea" not in infer_meal_periods("10:30-14:00", "粤式茶点")
    assert "early_tea" in infer_meal_periods("10:29-14:00", "粤式茶点")
    # 非粤式组不出 early_tea
    assert "early_tea" not in infer_meal_periods("08:00-22:00", "川湘辣味")
    assert "early_tea" not in infer_meal_periods("08:00-22:00", None)
    assert "early_tea" not in infer_meal_periods("08:00-22:00", "")


def test_afternoon_tea_cafe_teahouse_only():
    """afternoon_tea 双闸：咖啡烘焙/茶馆茶楼 ∧ 与 14:00–17:00 有交集。"""
    assert infer_meal_periods("10:00-20:00", "咖啡烘焙") == [
        "lunch",
        "afternoon_tea",
        "dinner",
    ]
    assert infer_meal_periods("10:00-20:00", "茶馆茶楼") == [
        "lunch",
        "afternoon_tea",
        "dinner",
    ]
    # 14:00 整点收打烊 → 无交集
    assert "afternoon_tea" not in infer_meal_periods("09:00-14:00", "咖啡烘焙")
    # 非茶咖组不出
    assert "afternoon_tea" not in infer_meal_periods("10:00-20:00", "火锅串串")
    assert "afternoon_tea" not in infer_meal_periods("10:00-20:00", None)


def test_multi_window_union_rules():
    """多段窗口任一段命中即算（午市+晚市分段）。"""
    assert infer_meal_periods("11:00-14:00,17:00-21:00", None) == ["lunch", "dinner"]
    assert infer_meal_periods("10:00-14:00,17:00-02:00", None) == [
        "lunch",
        "dinner",
        "late_night",
    ]


def test_all_day_place_gets_all_base_periods():
    assert infer_meal_periods("00:00-24:00", None) == [
        "breakfast",
        "lunch",
        "dinner",
        "late_night",
    ]
    assert infer_meal_periods("全年全天开放", "粤式茶点") == [
        "early_tea",
        "breakfast",
        "lunch",
        "dinner",
        "late_night",
    ]


def test_unparsable_hours_return_empty():
    assert infer_meal_periods("仅夜场（约19:30）", None) == []
    assert infer_meal_periods(None, "粤式茶点") == []
    assert infer_meal_periods("", None) == []


# --- _allowed_slots_for 显式优先切换 ---------------------------------------


def test_allowed_slots_explicit_meal_periods_win():
    """显式 meal_periods 直接映射槽位，不看营业时间。"""
    assert _allowed_slots_for("10:00-22:00", None, ["lunch", "dinner"]) == frozenset(
        {"lunch", "dinner"}
    )
    assert _allowed_slots_for(None, None, ["dinner"]) == frozenset({"dinner"})
    assert _allowed_slots_for(None, None, ["late_night"]) == frozenset({"dinner"})
    assert _allowed_slots_for("00:00-24:00", None, ["breakfast"]) == frozenset(
        {"lunch"}
    )
    assert _allowed_slots_for(None, None, ["early_tea"]) == frozenset({"lunch"})
    assert _allowed_slots_for(None, None, ["afternoon_tea"]) == frozenset({"lunch"})
    # 仅晚市餐秀：显式 dinner 锁死单槽
    assert _allowed_slots_for("11:00-21:00", None, ["dinner"]) == frozenset(
        {"dinner"}
    )


def test_allowed_slots_empty_or_unknown_falls_back():
    """空列表/缺失/全未识别 → 原营业时间推断行为完全不变。"""
    # 原 evening/morning 语义
    assert _allowed_slots_for("17:00-23:00", None, None) == frozenset({"dinner"})
    assert _allowed_slots_for("06:00-10:00", None, None) == frozenset({"lunch"})
    assert _allowed_slots_for("09:00-17:00", None, None) == frozenset(
        {"lunch", "dinner"}
    )
    # pois 行无该键 → None
    assert _allowed_slots_for("17:00-23:00", None, []) == frozenset({"dinner"})
    assert _allowed_slots_for(None, "evening", []) == frozenset({"dinner"})
    assert _allowed_slots_for(None, "morning", None) == frozenset({"lunch"})
    # 未知餐段值不裁槽（防御脏数据）
    assert _allowed_slots_for("09:00-17:00", None, ["weird"]) == frozenset(
        {"lunch", "dinner"}
    )


def test_candidate_from_poi_dict_chain():
    """candidate_from_poi_dict：pois 行无 meal_periods 走原逻辑；带值则生效。"""
    base = {
        "name": "红鼎宴",
        "location": {"lon": 120.0, "lat": 30.0},
        "opening_hours": "周一至周日 10:00-22:00",
        "category": "餐饮服务;中餐厅",
    }
    cand = candidate_from_poi_dict(base)
    assert cand is not None
    assert cand.allowed_slots == frozenset({"lunch", "dinner"})  # 原推断不变

    cand2 = candidate_from_poi_dict({**base, "meal_periods": ["dinner"]})
    assert cand2 is not None
    assert cand2.allowed_slots == frozenset({"dinner"})  # 显式优先

    cand3 = candidate_from_poi_dict({**base, "meal_periods": []})
    assert cand3 is not None
    assert cand3.allowed_slots == frozenset({"lunch", "dinner"})  # 空列表原逻辑
