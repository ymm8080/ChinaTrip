# -*- coding: utf-8 -*-
"""时间预算软闸 + 同档短时长优先（2026-11-02 拍板「时间约束是软闸，
不是硬闸；被闸时两个同等级的倾向于选时间短的」）规则锁定。

直接调用 PlanningAgent._deterministic_selection（静态方法，零 LLM/零网络）：
- 软闸：预算 360 分钟恰好被 3×120 占满时，第 4 个同档点不再被「全满
  出局」硬闸丢弃——软闸放行超额落位（求解层按真实时窗收口），仅
  4 个/日闸（铁律 6 口径的常识闸）保持硬闸；
- 短者优先：同档两点争最后一个每日名额时，短时长先占位。
"""

from app.services.agent.plan import PlanningAgent


def _cand(name: str, minutes: int, *, lon=108.95, lat=34.26) -> dict:
    return {
        "name": name,
        "city": "西安",
        "category": "attraction",
        "suggested_duration_min": minutes,
        "location": (lon, lat),
        "source": "5a",
        "tags": ["5a"],
    }


def _pick(candidates, days=1):
    picked = PlanningAgent._deterministic_selection(
        candidates, days, {"西安": (1, days)}
    )
    return [p["name"] for p in picked]


def test_time_budget_is_soft_gate_not_drop():
    # 3×120=360 恰好满预算；第 4 个同档点旧口径会被硬闸出局，软闸后照排。
    cands = [_cand(f"点{i}", 120) for i in range(1, 5)]
    names = _pick(cands)
    assert sorted(names) == ["点1", "点2", "点3", "点4"]


def test_same_tier_prefers_shorter_when_gated():
    # 3×40=120 已占，剩余预算装得下 60 也装得下 240，但每日只剩一个名额
    # （4 个/日闸）——同档被闸时短时长 60 先占位，240 出局。
    # 坐标彼此错开 >1.5km（2026-11-07 并卡拍板：≤1km 同街族件豁免
    # 4/日硬计数闸，同点夹具五点并一族全进——验闸封顶下的短者优先
    # 须独立点）。
    cands = [
        _cand("小一", 40, lon=108.95),
        _cand("小二", 40, lon=108.97),
        _cand("小三", 40, lon=108.99),
        _cand("长点", 240, lon=109.01),
        _cand("短点", 60, lon=109.03),
    ]
    names = _pick(cands)
    assert "短点" in names
    assert "长点" not in names
