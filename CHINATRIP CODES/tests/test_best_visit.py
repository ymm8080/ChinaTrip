"""best_visit 模块单元测试 — SLOTS 契约 + 营业时间粗推。

apply_rules 规则层已退役（2026-11-17 用户拍板「best visit time 不能走
HEURISTIC」），相应测试随层删除。
"""

from app.services.best_visit import SLOTS, infer_slot_from_hours


def test_slots_order_is_contract():
    assert SLOTS == ("sunrise", "morning", "afternoon", "evening", "sunset", "any")


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
