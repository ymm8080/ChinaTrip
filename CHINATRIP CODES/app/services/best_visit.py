"""best_visit_time 启发式规则层 — 三层回填的第一层（纯规则、零成本）.

POI 底库为每个景点补 best_visit_time 枚举（见 SLOTS），solver 消费它
实现「夜景排晚上」。本层只认名称/类别/营业时间里的明确信号，认不出
一律返回 None（列默认值 "any" 由 DB 层兜底，规则层绝不产出 "any"）。
后续 LLM 层、携程回源层另行回填，不在本模块。
"""

from __future__ import annotations

import re

SLOTS = ("sunrise", "morning", "afternoon", "evening", "sunset", "any")

# 名称规则：按序匹配，先命中先返回。保守起见只放明确信号——
# 「洪崖洞」这类名字本身无夜信号的 POI 绝不能误伤（夜景语义
# 由「洪崖洞夜景」这类显式命名或后续 LLM 层补充）。
RULES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            "夜市|夜景|夜游|灯光秀|音乐喷泉|酒吧街|夜(.*)(街|市)|两江夜游|不夜城"
        ),
        "evening",
    ),
    (re.compile("日落|夕阳|晚霞|日出日落|观景台|观景平台|山顶|摩天轮"), "sunset"),
    (re.compile("日出|朝阳|晨曦"), "sunrise"),
    (re.compile("晨练|早市"), "morning"),
]

# 类别规则（apply_rules 在名称之后兜底）：只认明确的英文类别信号；
# park→any 之类宽泛映射不写（any 是列默认值，不归规则层管）。
_CATEGORY_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile("viewpoint", re.IGNORECASE), "sunset"),
    (re.compile("night", re.IGNORECASE), "evening"),
]

_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")


def apply_rules(name: str | None, category: str | None = None) -> str | None:
    """名称规则优先、类别规则兜底；任一命中即返回，无命中返回 None."""
    if name:
        for pattern, slot in RULES:
            if pattern.search(name):
                return slot
    if category:
        for pattern, slot in _CATEGORY_RULES:
            if pattern.search(category):
                return slot
    return None


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
