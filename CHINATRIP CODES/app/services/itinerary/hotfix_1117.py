"""2026-11-17 incident hotfix (session 24379abd, Beijing 2-day, 5 musts).

Three symptoms, three passes — all pure functions on ItineraryPlan, wired
into the api read gate (inside _audit_must_coverage) so both fresh
generations and old sessions self-heal on GET:

1. evict_fillers_when_must_unseated  (B-02): while a requested must is
   untimed/unplaced, unrequested fillers on its day yield (user rule:
   必去优先于未请求点).
2. evict_pre_remote_fillers  (B-03a): on a remote day nothing unrequested
   may sit before the remote visit — 天安门 → direct departure is the only
   legal shape (E-1).
3. retime_remote_day_from_access  (B-03b/c, conservative): remote-day card
   times are corrected only when inconsistent with the shuttle timetable;
   a user-chosen departure (access_chosen_depart) and already-consistent
   times are never overridden. Card ≡ leg by construction; the lunch
   placeholder anchors at the remote site (先午餐后游览).

Untimed must cards themselves are demoted by request_coverage.
demote_untimed_musts (B-01): a must either has concrete times or lands in
unplaced with a disclosure — a timeless grey card is not a state.
"""

from __future__ import annotations

from datetime import time as _time
from typing import TYPE_CHECKING, Optional

from .models import DayPlan, TransferItem, VisitItem

if TYPE_CHECKING:  # pragma: no cover
    from .models import ItineraryPlan

DEFAULT_GATEWAY_TAXI_MINUTES = 15
REMOTE_VISIT_END_LIMIT = 18 * 60 + 30  # don't retime into the evening band


def _n(lang: str, zh: str, en: str) -> str:
    return en if (lang or "zh") == "en" else zh


def _mins(t: Optional[_time]) -> Optional[int]:
    if t is None:
        return None
    return t.hour * 60 + t.minute


def _hm(minutes: int) -> str:
    return "%02d:%02d" % (minutes // 60, minutes % 60)


def _hhmm_to_min(text: str) -> int:
    hh, mm = str(text).split(":")
    return int(hh) * 60 + int(mm)


def _is_filler(item) -> bool:
    """Unrequested fill only: engine-added, not user-owned. User items are
    pinned / must / soft_pin / created / curated; food & hotel are skeleton."""
    return (
        isinstance(item, VisitItem)
        and (item.category or "") not in ("food", "hotel")
        and not item.pinned
        and not getattr(item, "must", False)
        and not getattr(item, "soft_pin", False)
        and not getattr(item, "created", False)
        and not getattr(item, "curated", False)
    )


def _is_remote(item) -> bool:
    if not isinstance(item, VisitItem):
        return False
    # 餐/酒店骨架卡不算远郊点：它们会携带相邻接驳腿的字段（如午饭挂出
    # 班腿、晚饭挂回城腿），误判会把餐卡当远郊点重排（24379abd 复验
    # 发现的噪音源）。
    if (item.category or "") in ("food", "hotel"):
        return False
    if getattr(item, "remote", False):
        return True
    if getattr(item, "access_mode", None):
        return True
    return getattr(item, "access_ride_minutes", None) is not None


def _untimed_musts(plan: "ItineraryPlan") -> list[VisitItem]:
    return [
        v
        for d in plan.days
        for v in d.items
        if isinstance(v, VisitItem)
        and v.start_time is None
        and (v.pinned or getattr(v, "must", False))
        and (v.category or "") not in ("food", "hotel")
    ]


def evict_fillers_when_must_unseated(
    plan: "ItineraryPlan",
    *,
    must_names: list[str] | None = None,
    lang: str = "zh",
) -> list[str]:
    """B-02: unrequested fillers yield on days where a requested must is
    unseated (untimed card in days, or in unplaced with a day hint)."""
    notes: list[str] = []
    unseated_days: set[int] = set()
    for v in _untimed_musts(plan):
        unseated_days.add(v.day)
    names = {str(n or "").strip() for n in (must_names or [])}
    for u in plan.unplaced or []:
        if names and str(u.name or "").strip() in names and u.day_hint:
            unseated_days.add(u.day_hint)
    if not unseated_days:
        return notes
    for day in plan.days:
        if day.day not in unseated_days:
            continue
        for item in list(day.items):
            if not _is_filler(item):
                continue
            day.items.remove(item)
            notes.append(
                _n(
                    lang,
                    f"必去优先：第{day.day}天有必去未排上，「{item.name}」"
                    "已让位移出——必去排上或另行指定后再补",
                    f"Day {day.day}: must-visit first — filler "
                    f"'{item.name}' gave way while a requested must "
                    "is unseated",
                )
            )
    return notes


def evict_pre_remote_fillers(plan: "ItineraryPlan", *, lang: str = "zh") -> list[str]:
    """B-03a: on a remote day, no unrequested item may precede the remote
    visit (its outbound access leg). 天安门 → direct departure (E-1)."""
    notes: list[str] = []
    for day in plan.days:
        remote = [v for v in day.items if _is_remote(v) and v.start_time is not None]
        if not remote:
            continue
        first_start = min(_mins(v.start_time) for v in remote)
        for item in list(day.items):
            if not _is_filler(item):
                continue
            item_end = _mins(item.end_time) or _mins(item.start_time) or 0
            if item_end > first_start:
                continue
            day.items.remove(item)
            notes.append(
                _n(
                    lang,
                    f"第{day.day}天远郊出发优先：「{item.name}」在远郊点之前"
                    "已移出——晨锚后直接出发去远郊",
                    f"Day {day.day}: remote departure first — "
                    f"'{item.name}' removed from before the remote visit",
                )
            )
    return notes


def _gateway_taxi_minutes(day: DayPlan, visit_idx: int) -> int:
    """Taxi to the boarding gateway: prefer the outbound access detail
    attached to the item right before the remote visit; else default."""
    for back in range(visit_idx - 1, -1, -1):
        prev = day.items[back]
        detail = getattr(prev, "next_leg_detail", None)
        if isinstance(detail, dict) and detail.get("mode") == "access":
            taxi = detail.get("taxi_minutes")
            if isinstance(taxi, int) and taxi >= 0:
                return taxi
        if isinstance(prev, VisitItem) and (prev.category or "") not in (
            "food",
            "hotel",
        ):
            break
    return DEFAULT_GATEWAY_TAXI_MINUTES


def retime_remote_day_from_access(
    plan: "ItineraryPlan", *, lang: str = "zh"
) -> list[str]:
    """B-03b/c（保守版）：远郊日时刻只在「不一致」时纠正，绝不重选班次。

    合法形态 = 班次表推出的到站 +（先午餐时长的）午饭；判定顺序：
    ①用户点名班次（access_chosen_depart）→ 以它为准；
    ②当前游览开始时刻已与某班次一致 → 只对齐午饭（时刻/锚点）；
    ③都不一致（事故形态：午饭锚在城里、卡时刻=午饭结束零车程）→
      从前站结束+打车推最早可乘班次重排，卡时刻=班次时刻（卡≡腿）。
    骑窗/游后午饭是合法形态不搬（b909d60 拍板口径）；幂等。
    """
    notes: list[str] = []
    for day in plan.days:
        for idx, visit in enumerate(day.items):
            if not _is_remote(visit) or visit.start_time is None:
                continue
            deps = [
                _hhmm_to_min(d)
                for d in (getattr(visit, "access_depart_times", None) or [])
            ]
            ride = getattr(visit, "access_ride_minutes", None)
            last_mile = getattr(visit, "access_last_mile_minutes", None) or 0
            if not deps or not ride:
                continue
            visit_start_now = _mins(visit.start_time)
            visit_dur = visit.duration_minutes or 120
            lunch = next(
                (
                    v
                    for v in day.items
                    if isinstance(v, VisitItem)
                    and (v.item_id or "").startswith("food-lunch-ph")
                    and v is not visit
                ),
                None,
            )
            lunch_before = bool(
                lunch is not None
                and _mins(lunch.start_time) is not None
                and _mins(lunch.start_time) <= visit_start_now
            )
            lunch_dur = (lunch.duration_minutes or 60) if lunch_before else 0
            legal = {d + int(ride) + int(last_mile) + lunch_dur for d in deps}
            chosen = getattr(visit, "access_chosen_depart", None)
            target: int | None = None
            if chosen:
                try:
                    target = (
                        _hhmm_to_min(chosen) + int(ride) + int(last_mile) + lunch_dur
                    )
                except ValueError:
                    target = None
            elif visit_start_now in legal:
                target = visit_start_now  # 已一致：只对齐午饭，不动班次
            else:
                prev_end = 0
                for back in range(idx - 1, -1, -1):
                    prev = day.items[back]
                    if isinstance(prev, TransferItem):
                        prev_end = _mins(prev.end_time) or 0
                        break
                    if isinstance(prev, VisitItem) and (prev.category or "") != "food":
                        prev_end = _mins(prev.end_time) or _mins(prev.start_time) or 0
                        break
                earliest = prev_end + _gateway_taxi_minutes(day, idx)
                dep = next((d for d in sorted(deps) if d >= earliest), None)
                if dep is None:
                    continue
                target = dep + int(ride) + int(last_mile) + lunch_dur
            if target is None or target + visit_dur > REMOTE_VISIT_END_LIMIT:
                continue
            changed = False
            if (
                lunch is not None
                and lunch_before
                and _mins(lunch.start_time) != target - lunch_dur
            ):
                ls = target - lunch_dur
                lunch.start_time = _time(ls // 60, ls % 60)
                lunch.end_time = _time((ls + lunch_dur) // 60, (ls + lunch_dur) % 60)
                if visit.location is not None:
                    lunch.anchor_location = visit.location
                    lunch.address = visit.address or lunch.address
                changed = True
            if visit_start_now != target:
                visit.start_time = _time(target // 60, target % 60)
                visit.end_time = _time(
                    (target + visit_dur) // 60, (target + visit_dur) % 60
                )
                changed = True
            if changed:
                arrive = target - lunch_dur
                dep_txt = _hm(arrive - int(ride) - int(last_mile))
                lunch_note = (
                    f"，先午餐 {_hm(arrive)}-{_hm(target)} 在{visit.name}"
                    if (lunch is not None and lunch_before)
                    else ""
                )
                notes.append(
                    _n(
                        lang,
                        f"第{day.day}天接驳对齐：{dep_txt} 班 → "
                        f"{_hm(arrive)} 到{visit.name}{lunch_note}，"
                        f"游览 {_hm(target)}-{_hm(target + visit_dur)}"
                        "（卡时刻=班次时刻）",
                        f"Day {day.day}: card times aligned to the shuttle "
                        f"timetable ({dep_txt}); visit {_hm(target)}-"
                        f"{_hm(target + visit_dur)}",
                    )
                )
    return notes
