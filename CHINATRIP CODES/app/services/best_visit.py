"""best_visit_time 枚举契约与营业时间粗推（规则推断层已退役）.

SLOTS 是 best_visit_time 的枚举契约；infer_slot_from_hours 供餐饮营业
窗推断（restaurants.py）复用。

2026-11-17 用户拍板「best visit time 不能走 HEURISTIC」：名称/类别规则
推断（apply_rules）整层退役——「category=viewpoint → sunset」一刀切曾
把都市观光塔（上海中心大厦/环球金融中心/金茂观光厅，白天 08:30 开门）
标成夜属性，豁免 16:00 白天入场闸（16:47/19:00 排期穿透案）。库值只来
自 llm/ctrip 回填层与人工修正，排程侧只透传，绝不现场脑补。
"""

from __future__ import annotations

import re

SLOTS = ("sunrise", "morning", "afternoon", "evening", "sunset", "any")

_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")


def infer_slot_from_hours(opening_hours: str | None) -> str | None:
    """从营业时间串粗推时段；解析不了或常规日场返回 None.

    例："17:00-23:00" 仅夜间营业 → evening；"06:00-10:00" 仅清晨 →
    morning；"09:00-17:00" 常规日场 → None。跨零点窗口按 +24h 归一。
    """
    if not opening_hours:
        return None
    times = [
        (int(h), int(m))
        for h, m in _TIME_RE.findall(opening_hours)
        if int(h) < 24 and int(m) < 60
    ]
    if len(times) < 2:
        return None
    open_min = times[0][0] * 60 + times[0][1]
    close_min = times[-1][0] * 60 + times[-1][1]
    if close_min <= open_min:  # 跨零点（如 19:00-01:00）
        close_min += 24 * 60
    if open_min >= 17 * 60:  # 17:00 后才开门 → 仅夜间营业
        return "evening"
    if open_min >= 6 * 60 and close_min <= 10 * 60:  # 仅清晨窗口
        return "morning"
    return None
