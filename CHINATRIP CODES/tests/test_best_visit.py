"""best_visit 规则层单元测试 — 纯函数，无 DB 无网络。"""

from app.services.best_visit import (
    _CATEGORY_RULES,
    RULES,
    SLOTS,
    apply_rules,
    infer_slot_from_hours,
)


def test_slots_order_is_contract():
    assert SLOTS == ("sunrise", "morning", "afternoon", "evening", "sunset", "any")


def test_rules_only_emit_valid_non_any_slots():
    for _, slot in RULES + _CATEGORY_RULES:
        assert slot in SLOTS and slot != "any"


# --- apply_rules: 名称规则 -------------------------------------------------


def test_hongyadong_plain_name_has_no_night_signal():
    # 「洪崖洞」名字本身无夜信号，规则绝不能误伤；夜景语义只认显式命名。
    assert apply_rules("洪崖洞") is None


def test_evening_names():
    assert apply_rules("洪崖洞夜景") == "evening"
    assert apply_rules("重庆夜市") == "evening"
    assert apply_rules("解放碑灯光秀") == "evening"
    assert apply_rules("两江夜游") == "evening"
    assert apply_rules("长沙夜市街") == "evening"  # 夜(.*)(街|市)
    assert apply_rules("西安大唐不夜城") == "evening"
    assert apply_rules("西湖音乐喷泉") == "evening"


def test_sunset_names():
    assert apply_rules("南山一棵树观景台") == "sunset"
    assert apply_rules("泰山山顶") == "sunset"
    assert apply_rules("天津之眼摩天轮") == "sunset"
    assert apply_rules("海边日落") == "sunset"


def test_sunrise_names():
    assert apply_rules("峨眉山金顶日出") == "sunrise"
    assert apply_rules("旗顶朝阳") == "sunrise"
    # 观景平台信号优先级高于朝阳（sunset 规则在 sunrise 之前）
    assert apply_rules("朝阳观景平台") == "sunset"


def test_morning_names():
    assert apply_rules("人民公园早市") == "morning"
    assert apply_rules("滨水晨练步道") == "morning"


# --- apply_rules: 类别规则与名称优先级 --------------------------------------


def test_category_signals():
    assert apply_rules("某无名点", "viewpoint") == "sunset"
    assert apply_rules("某无名点", "Night Market") == "evening"


def test_name_beats_category():
    # 名称优先：金顶日出(sunrise) 不被类别 viewpoint(sunset) 覆盖
    assert apply_rules("峨眉山金顶日出", "viewpoint") == "sunrise"


def test_no_hit_returns_none():
    assert apply_rules("西湖") is None
    assert apply_rules("西湖", "park") is None
    assert apply_rules(None, "park") is None
    assert apply_rules(None, None) is None
    assert apply_rules("") is None
    assert apply_rules("洪崖洞", "sight") is None


# --- infer_slot_from_hours: 营业时间粗推 ------------------------------------


def test_night_only_hours_infer_evening():
    assert infer_slot_from_hours("17:00-23:00") == "evening"
    assert infer_slot_from_hours("19:30-02:00") == "evening"  # 跨零点


def test_early_only_hours_infer_morning():
    assert infer_slot_from_hours("06:00-10:00") == "morning"


def test_regular_daytime_hours_infer_none():
    assert infer_slot_from_hours("09:00-17:00") is None
    assert infer_slot_from_hours("08:30-17:00") is None


def test_garbage_or_missing_hours_infer_none():
    assert infer_slot_from_hours("全年全天开放") is None
    assert infer_slot_from_hours("25:99-30:00") is None
    assert infer_slot_from_hours("17:00") is None  # 只有一端，不成窗
    assert infer_slot_from_hours("") is None
    assert infer_slot_from_hours(None) is None
