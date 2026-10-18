"""Itinerary mutation pipeline (design §6.0/§6.4, iron rule 0).

One pipeline for every change source — LLM rerank, manual drag, snapshot
restore, solver output. apply -> validate (hard rules) -> summarize.
Pure functions only: no I/O, no LLM, no DB; inputs are never mutated.
"""

from datetime import time

from app.services.itinerary.models import (
    ChangeSummary,
    CrowdProfile,
    DiffOp,
    ItineraryPlan,
    PoiHours,
    RuleSeverity,
    TransferItem,
    ValidationReport,
    VisitItem,
)
from app.services.itinerary.rules import (
    _minutes,
    validate_change_scope,
    validate_pinned,
    validate_plan,
)

_MINUTES_PER_DAY = 24 * 60


class PipelineError(ValueError):
    """非法 diff op（铁律 0 管线入口直接拒绝）。"""


def _find_item(plan: ItineraryPlan, item_id: str | None) -> VisitItem | TransferItem:
    if item_id is None:
        raise PipelineError("op 缺少 item_id")
    for d in plan.days:
        for i in d.items:
            if i.item_id == item_id:
                return i
    raise PipelineError(f"item 不存在: {item_id}")


def _recompute_end_times(plan: ItineraryPlan) -> None:
    """Refill end_time wherever start_time + duration_minutes are known."""
    for d in plan.days:
        for i in d.items:
            if i.start_time is not None and i.duration_minutes is not None:
                end = (_minutes(i.start_time) + i.duration_minutes) % _MINUTES_PER_DAY
                i.end_time = time(end // 60, end % 60)


def apply_diffs(plan: ItineraryPlan, diffs: list[DiffOp]) -> ItineraryPlan:
    """Apply diff ops onto a deep copy; the input plan is never touched."""
    new_plan = plan.model_copy(deep=True)
    day_by_no = {d.day: d for d in new_plan.days}
    for op in diffs:
        if op.op == "add":
            if op.item is None:
                raise PipelineError("add op 缺少 item")
            target = day_by_no.get(op.item.day)
            if target is None:
                raise PipelineError(f"add op 目标第 {op.item.day} 天不存在")
            target.items.append(op.item.model_copy(deep=True))
        elif op.op == "remove":
            item = _find_item(new_plan, op.item_id)
            day_by_no[item.day].items.remove(item)
        elif op.op == "move":
            if op.new_day is None:
                raise PipelineError("move op 缺少 new_day")
            item = _find_item(new_plan, op.item_id)
            target = day_by_no.get(op.new_day)
            if target is None:
                raise PipelineError(f"move op 目标第 {op.new_day} 天不存在")
            if op.new_start_time is not None:
                item.start_time = op.new_start_time
            if op.new_day != item.day:
                day_by_no[item.day].items.remove(item)
                item.day = op.new_day
                target.items.append(item)
        elif op.op == "retime":
            if op.new_start_time is None:
                raise PipelineError("retime op 缺少 new_start_time")
            item = _find_item(new_plan, op.item_id)
            item.start_time = op.new_start_time
        else:  # pragma: no cover - DiffOp literal makes this unreachable
            raise PipelineError(f"未知 op: {op.op}")
    _recompute_end_times(new_plan)
    return new_plan


def _item_name(item: VisitItem | TransferItem) -> str:
    if isinstance(item, VisitItem):
        return item.name
    return f"{item.from_city}→{item.to_city}"


def summarize_changes(
    diffs: list[DiffOp], *, plan: ItineraryPlan | None = None
) -> ChangeSummary:
    """Iron rule 19 output: one human-readable line per diff + affected count."""
    names: dict[str, str] = {}
    days: dict[str, int] = {}
    if plan is not None:
        for d in plan.days:
            for i in d.items:
                names[i.item_id] = _item_name(i)
                days[i.item_id] = i.day
    lines: list[str] = []
    seen: set[str] = set()
    for op in diffs:
        oid = op.item_id or (op.item.item_id if op.item is not None else None)
        if oid is not None:
            seen.add(oid)
        if op.op == "add" and op.item is not None:
            lines.append(f"第{op.item.day}天 新增 {_item_name(op.item)}")
        elif op.op == "remove":
            day_part = f"第{days[oid]}天 " if oid in days else ""
            lines.append(f"{day_part}移除 {names.get(oid, oid)}")
        elif op.op == "move":
            tm = (
                f" 到 {op.new_start_time.strftime('%H:%M')}"
                if op.new_start_time is not None
                else ""
            )
            lines.append(f"第{op.new_day}天 移动 {names.get(oid, oid)}{tm}")
        elif op.op == "retime":
            day_part = f"第{days[oid]}天 " if oid in days else ""
            tm = (
                op.new_start_time.strftime("%H:%M")
                if op.new_start_time is not None
                else "未指定"
            )
            lines.append(f"{day_part}调整 {names.get(oid, oid)} 时间到 {tm}")
    return ChangeSummary(change_summary=lines, affected_items_count=len(seen))


def mutate(
    plan: ItineraryPlan,
    diffs: list[DiffOp],
    *,
    poi_hours: list[PoiHours],
    crowd_profile: CrowdProfile = CrowdProfile.normal,
    from_day: int | None = None,
    old_plan: ItineraryPlan | None = None,
) -> tuple[ItineraryPlan, ValidationReport, ChangeSummary]:
    """Iron rule 0 one-shot pipeline: apply -> hard-validate -> summarize.

    When ``old_plan`` is given, scope (rule 10, needs ``from_day``) and pinned
    (rule 19) checks are stacked on top of the static plan validation.
    """
    new_plan = apply_diffs(plan, diffs)
    report = validate_plan(new_plan, poi_hours=poi_hours, crowd_profile=crowd_profile)
    extra = []
    if old_plan is not None and from_day is not None:
        extra += validate_change_scope(old_plan, new_plan, from_day=from_day).violations
    if old_plan is not None:
        extra += validate_pinned(old_plan, new_plan).violations
    if extra:
        combined = list(report.violations) + extra
        has_error = any(v.severity == RuleSeverity.error for v in combined)
        report = ValidationReport(ok=not has_error, violations=combined)
    summary = summarize_changes(diffs, plan=old_plan or new_plan)
    return new_plan, report, summary
