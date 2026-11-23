# -*- coding: utf-8 -*-
"""C-25 文本次日钉（R25「按我写的顺序排」选边）。

用户贴进来的行程写明「DayN / 第N天」时，站点确认卡上问一次：keep=按写明的
天钉本约束（该必去只在指定天在场，日内顺序仍由求解器在当天内优化）；replan=按
天气/地理自由排（day_hint 全 None，本约束不生效）。硬钉语义与 legacy
forced_days 一致（「点名天优先，地理择日不许改天」）；指定天装不下时由既有
unplaced 披露与 degenerate/fallback 链如实报。
"""

from __future__ import annotations


def add_c25_must_days(bundle, enriched) -> None:
    request = enriched.snapshot.request
    day_of: dict[str, int] = {}
    days = int(getattr(request, "days", 0) or 0)
    for req in getattr(request, "musts", ()) or ():
        hint = getattr(req, "day_hint", None)
        if isinstance(hint, int) and 1 <= hint <= days:
            day_of[str(req.rid)] = hint
    if not day_of:
        return
    for cand in enriched.snapshot.candidates:
        if cand.kind != "requested" or not cand.rid:
            continue
        want = day_of.get(str(cand.rid))
        if want is None:
            continue
        for day in bundle.days:
            if int(day) != want:
                bundle.model.Add(bundle.presence[(cand.cid, day)] == 0)
