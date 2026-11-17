"""F-12 hours windows + entry caps (semantics ported verbatim from solver).

Source of truth: app/services/itinerary/solver.py —
  _hours_open_form / _hours_evening_only / generic_entry_cap
  constants at lines 296-391 (990 generic, 930 big, 1020 evening-only,
  open-form 06:00-22:00, EVENING_OK sets).

Model-level difference (intentional, per 晚闸口径 v2): the open-form
exemption is applied HERE (the model has no deletion layer to do it in);
the legacy scheduler keeps the cap internally and exempts at the deletion
layer — test_trip_solver_inputs.py documents this divergence.
"""

from __future__ import annotations

import re
from typing import Optional

GENERIC_ENTRY_CAP_MINUTES = 16 * 60 + 30  # 990, c93a712
BIG_SITE_ENTRY_CAP_MINUTES = 15 * 60 + 30  # 930
EVENING_ONLY_OPEN_MINUTES = 17 * 60  # 1020
OPEN_FORM_ALLDAY_OPEN_MAX = 6 * 60  # 360
OPEN_FORM_ALLDAY_CLOSE_MIN = 22 * 60  # 1320
BIG_SITE_MIN_MINUTES = 80  # scoring.BIG_SITE_MIN_MINUTES
EVENING_OK_CATEGORIES = frozenset({"food", "entertainment", "hotel", "transport"})
EVENING_OK_BEST = frozenset({"evening", "sunset", "show"})

_WINDOW_RE = re.compile(r"(\d{1,2}:\d{2})\s*[-–~至到]\s*(\d{1,2}:\d{2})")


def _to_min(text: str) -> Optional[int]:
    hh, mm = text.split(":")
    minutes = int(hh) * 60 + int(mm)
    return min(minutes, 24 * 60)


def parse_first_window(text: Optional[str]) -> Optional[tuple[int, int]]:
    """First HH:MM-HH:MM span in an opening-hours display string.

    Covers the G-01 patterns (今天07:30-18:30开放… / 周一至周日 00:00-24:00 /
    03:30-20:30 / 故宫多段文本取第一段). Seasonal multi-window parsing is
    fixture-v2 scope (audit M3); callers treat the result as an approximation.
    """
    if not text:
        return None
    match = _WINDOW_RE.search(text)
    if not match:
        return None
    opens = _to_min(match.group(1))
    closes = _to_min(match.group(2))
    if opens is None or closes is None or closes <= opens:
        return None
    return opens, closes


def is_open_form(window: Optional[tuple[int, int]]) -> bool:
    """无窗（商业街/citywalk）或全天窗（开 ≤06:00 且关 ≥22:00）→ 开放形态。"""
    if window is None:
        return True
    opens, closes = window
    return opens <= OPEN_FORM_ALLDAY_OPEN_MAX and closes >= OPEN_FORM_ALLDAY_CLOSE_MIN


def is_evening_only(window: Optional[tuple[int, int]]) -> bool:
    if window is None:
        return False
    return window[0] >= EVENING_ONLY_OPEN_MINUTES


def is_big_site(
    *,
    duration_min: Optional[int],
    category: Optional[str],
    best_visit_time: Optional[str],
    tier: Optional[int],
    pinned_with_time: bool = False,
) -> bool:
    """时长>80min、非街区(tier8)、非餐/酒店/演出、非夜属性的观光点。"""
    if pinned_with_time:
        return False
    if (category or "") in ("food", "hotel", "entertainment"):
        return False
    if (best_visit_time or "") in EVENING_OK_BEST:
        return False
    if tier == 8:
        return False
    return (duration_min or 0) > BIG_SITE_MIN_MINUTES


def is_theme_block(
    *,
    name: str,
    category: Optional[str],
    best_visit_time: Optional[str],
    pinned_with_time: bool = False,
) -> bool:
    """名含「街区」的演出/娱乐/街区行（沉浸式主题街区倾向晚场）。"""
    if pinned_with_time:
        return False
    if "街区" not in (name or ""):
        return False
    return (best_visit_time or "") == "show" or (category or "") in (
        "citywalk",
        "entertainment",
    )


def entry_cap_minutes(
    *,
    name: str,
    category: Optional[str],
    best_visit_time: Optional[str],
    opening_hours_text: Optional[str],
    duration_min: Optional[int],
    tier: Optional[int],
    pinned_with_time: bool = False,
) -> tuple[Optional[int], str]:
    """最晚开场分钟数；None = 豁免（返回豁免原因）。

    顺序逐条对齐 solver.generic_entry_cap：铁律19 → 夜属性(bvt) →
    夜类目 → 仅晚开放 → 主题街区 → （模型级新增）开放形态 → 大点 930 →
    普通 990。
    """
    window = parse_first_window(opening_hours_text)
    if pinned_with_time:
        return None, "iron-rule-19"
    if (best_visit_time or "") in EVENING_OK_BEST:
        return None, "evening-attr"
    if (category or "") in EVENING_OK_CATEGORIES:
        return None, "evening-cat"
    if is_evening_only(window):
        return None, "evening-only"
    if is_theme_block(
        name=name,
        category=category,
        best_visit_time=best_visit_time,
        pinned_with_time=pinned_with_time,
    ):
        return None, "theme-block"
    if is_open_form(window):
        return None, "open-form"
    if is_big_site(
        duration_min=duration_min,
        category=category,
        best_visit_time=best_visit_time,
        tier=tier,
        pinned_with_time=pinned_with_time,
    ):
        return BIG_SITE_ENTRY_CAP_MINUTES, "big-site"
    return GENERIC_ENTRY_CAP_MINUTES, "generic"
