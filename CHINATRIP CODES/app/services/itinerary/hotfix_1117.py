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

2026-11-17 慕田峪复验补刀：热修挪盘后腿字段要跟着重算——annotate 只在
生成期跑过，读闸撤掉的前补点会把旧腿留在卡上、去程接驳链无卡可挂
（api/plan.py 读闸在本模块任一 pass 有产出时重跑 annotate_legs）。
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
        # R12 交通桥卡（leg-bridge-*）是渲染件不是填充活动——绝不当
        # filler 撤（远郊日清场/必去让位两 pass 都不动它）。
        and not str(getattr(item, "item_id", "") or "").startswith("leg-bridge-")
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
    """无时刻必去卡（must 标记）——用户手钉卡（铁律 19）不算：钉住是
    用户自己的安排，不得因它触发让位/降级（test_untimed_response_strip
    出站口径：钉住卡保留在行程里）。"""
    return [
        v
        for d in plan.days
        for v in d.items
        if isinstance(v, VisitItem)
        and v.start_time is None
        and getattr(v, "must", False)
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
    # R12-E：引擎卡不带 must 标记——无时刻卡名字命中必去名册同判
    # （入场闸剥掉的必去也要让填充让位，live 实锤天坛/景山案）。
    for day in plan.days:
        for v in day.items:
            if (
                isinstance(v, VisitItem)
                and v.start_time is None
                and str(v.name or "").strip() in names
            ):
                unseated_days.add(day.day)
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


# ---------- R12-C: restaurant visit cards fold into meal cards ----------


def _is_restaurant_visit(item) -> bool:
    """真餐馆以「观光卡」形态出现（R12-M 之前的存量/回退形态，live 实锤
    2026-11-19 会话 6259415f：四季民福 [v4] 11:02 观光卡与午餐占位并列）：
    food 品类、有时刻、既非占位餐卡（engine meal-* 无 poi / legacy
    food-*-ph*）也非引擎命名餐卡（meal-lunch/dinner-* 带 poi）。"""
    from app.services.restaurants import is_dinner_placeholder, is_lunch_placeholder

    if not isinstance(item, VisitItem) or (item.category or "") != "food":
        return False
    iid = str(getattr(item, "item_id", "") or "")
    if iid.startswith(("meal-lunch", "meal-dinner")):
        return False  # 引擎餐卡（占位或命名顶卡）——不是孤儿观光卡
    if is_lunch_placeholder(item) or is_dinner_placeholder(item):
        return False
    return item.start_time is not None


def fold_restaurant_visit_cards(plan, *, lang: str = "zh") -> list[str]:
    """R12-C（2026-11-19 用户拍板「烤鸭店这类餐厅可以进行程、非常推荐进
    行程，但放在午餐/晚餐卡上」）：读闸自愈——把以观光卡形态出现的真餐馆
    折进当日对应时段的占位餐卡：占位卡顶替成命名餐卡（名字/坐标/POI/营业
    时间/时刻全取餐馆卡——R8-S2b 同形态），观光卡撤除。午段（<15:00）折
    午餐、晚段（≥15:00）折晚餐；对应槽无占位时不折（不发明新槽）。幂等。
    """
    from app.services.restaurants import is_dinner_placeholder, is_lunch_placeholder

    notes: list[str] = []
    for day in plan.days:
        orphans = [v for v in day.items if _is_restaurant_visit(v)]
        if not orphans:
            continue
        items = list(day.items)
        changed = False
        for orphan in orphans:
            start = _mins(orphan.start_time)
            if start is None:
                continue
            slot = "lunch" if start < 15 * 60 else "dinner"
            is_ph = is_lunch_placeholder if slot == "lunch" else is_dinner_placeholder
            target = next((v for v in items if v is not orphan and is_ph(v)), None)
            if target is None:
                continue
            # 占位卡顶替成命名餐卡：本体=餐馆卡，槽位 id 保留（餐卡身份）
            target.name = orphan.name
            target.name_en = getattr(orphan, "name_en", None)
            target.poi_id = orphan.poi_id
            if orphan.location is not None:
                target.location = orphan.location
            if getattr(orphan, "address", None):
                target.address = orphan.address
            target.opening_hours = orphan.opening_hours
            target.start_time = orphan.start_time
            target.end_time = orphan.end_time
            target.duration_minutes = orphan.duration_minutes
            target.anchor_from_prev = False
            if orphan.location is not None:
                target.anchor_location = orphan.location
            items.remove(orphan)
            changed = True
            notes.append(
                _n(
                    lang,
                    f"第{day.day}天「{orphan.name}」已折进{slot}餐卡"
                    "（餐厅进餐卡，不再与占位餐卡并列）",
                    f"Day {day.day}: '{orphan.name}' folded into the {slot} meal card",
                )
            )
        if changed:
            day.items = items
            day.items.sort(
                key=lambda i: (
                    (_mins(i.start_time) if i.start_time is not None else 24 * 60),
                    str(getattr(i, "item_id", "") or ""),
                )
            )
    return notes


# ---------- R12-E: entry-gated must rescue ----------


def rescue_entry_gated_musts(
    plan, *, must_names: list[str] | None = None, lang: str = "zh"
) -> list[str]:
    """R12-E（2026-11-19 用户令「指定的天坛为什么漏了，而没指定的景山插进
    去了」）：入场闸/读闸 heal 把**已排上的必去**推过入场闸剥成无时刻后，
    当天未请求的填充卡必须让位——必去顶进让出的窗口（入场时刻 ≤ 闸 +
    不与邻卡重叠）。营救不了的（无填充可让/窗放不下）保持无时刻，由
    evict_fillers_when_must_unseated 清场兜底。幂等：有时刻的必去不再触发。
    """
    from app.services.itinerary.solver import generic_entry_cap

    names = {str(n or "").strip() for n in (must_names or [])}
    notes: list[str] = []
    for day in plan.days:
        stripped = [
            v
            for v in day.items
            if isinstance(v, VisitItem)
            and v.start_time is None
            and str(v.name or "").strip() in names
        ]
        if not stripped:
            continue
        timed = sorted(
            (
                v
                for v in day.items
                if isinstance(v, VisitItem) and v.start_time is not None
            ),
            key=lambda v: (
                v.start_time.hour * 60 + v.start_time.minute,
                str(v.item_id or ""),
            ),
        )
        fills = [v for v in timed if _is_filler(v)]
        for must in stripped:
            dur = int(must.duration_minutes or 120)
            cap = generic_entry_cap(must, None)
            placed = False
            for fill in fills:
                if fill in day.items and not _is_filler(fill):
                    continue
                fs = fill.start_time.hour * 60 + fill.start_time.minute
                if cap is not None and fs > cap:
                    continue
                # 前一卡收尾 + 走行地板 = 最早可入
                prev_end = 0
                for v in timed:
                    if v is fill:
                        continue
                    ve = (v.end_time.hour * 60 + v.end_time.minute) if v.end_time else 0
                    if ve <= fs and ve > prev_end:
                        prev_end = ve
                start = max(fs, prev_end + 30)
                if cap is not None and start > cap:
                    continue
                # 后一卡开场 = 最晚须收
                next_start = 24 * 60
                for v in timed:
                    if v is fill:
                        continue
                    vs = v.start_time.hour * 60 + v.start_time.minute
                    if vs >= fs and vs < next_start:
                        next_start = vs
                if start + dur + 30 > next_start:
                    continue
                day.items.remove(fill)
                must.start_time = _time(start // 60 % 24, start % 60)
                end = start + dur
                must.end_time = _time(end // 60 % 24, end % 60)
                placed = True
                fills.remove(fill)
                notes.append(
                    _n(
                        lang,
                        f"必去优先：第{day.day}天「{must.name}」入场闸内改排 "
                        f"{_hm(start)}-{_hm(end)}，未请求的「{fill.name}」让位",
                        f"Day {day.day}: must-visit '{must.name}' rescheduled to "
                        f"{_hm(start)}-{_hm(end)} inside its entry gate; "
                        f"unrequested '{fill.name}' gave way",
                    )
                )
                break
            if not placed:
                # 营救不了：让给 evict pass 清场（该必去仍无时刻）
                continue
        if notes and day.items:
            day.items.sort(
                key=lambda i: (
                    (
                        (i.start_time.hour * 60 + i.start_time.minute)
                        if getattr(i, "start_time", None) is not None
                        else 24 * 60
                    ),
                    str(getattr(i, "item_id", "") or ""),
                )
            )
    return notes
