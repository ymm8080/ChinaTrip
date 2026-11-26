"""Golden assertion evaluators (M7 schema, P2-A).

Per scenario, an ordered list of `{type, args}` assertions (see
tests/golden/*.json `expect`). Each evaluator runs against ANY PlanView
(legacy recording or model solution) and returns one result dict:

    {"type", "engine", "status": pass|fail|pending|skipped, "detail"}

- **pass**    — holds on this view.
- **fail**    — violated on this view (a real diff finding; on the legacy
  side these are the incident's documented defects, on the model side
  they are what P2-B must burn down).
- **pending** — the machinery to satisfy/check it lands later (meal cards
  F-31 → P1-F, disclosure templates F-33 → P1-F). Never a fake pass.
- **skipped** — the precondition is absent in this scenario (e.g. a
  time_range pinned to the 升旗 timetable but the scenario sets no pin).

Exact times are asserted only where a timetable fixes them (M7); shape
invariants otherwise. Two schema extensions beyond M7 support the C-05
endpoint-day family: `day_start_floor` / `day_end_ceiling`; P2-B adds
`remote_day_purity` / `span_cap` / `city_coherence` (C-06/C-15, Q1, C-07
families).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from .views import KIND_VISIT, CardView, PlanView, hhmm_to_min, min_to_hhmm

if TYPE_CHECKING:  # pragma: no cover
    from ..inputs.enrich import EnrichedSnapshot
    from ..types import FactSnapshot


@dataclass
class AssertContext:
    snapshot: "FactSnapshot"
    enriched: Optional["EnrichedSnapshot"] = None  # None → cap checks skip


def _result(kind: str, assertion: dict, engine: str, detail: str) -> dict:
    return {
        "type": assertion.get("type"),
        "engine": engine,
        "status": kind,
        "detail": detail,
    }


def _has_pin(snapshot: "FactSnapshot", name: str) -> bool:
    for pin in getattr(snapshot.request, "pins", ()) or ():
        for req in list(snapshot.request.musts) + list(snapshot.request.wishes):
            if req.rid == pin.rid and req.name == name:
                return True
    return False


# --- per-type evaluators (engine-neutral) -----------------------------------


def _eval_sequence(view: PlanView, args: dict) -> tuple[str, str]:
    day = int(args["day"])
    order = list(args["order"])
    cards = view.sorted_day(day)
    positions: list[int] = []
    for want in order:
        hits = [i for i, c in enumerate(cards) if c.name == want]
        if not hits:
            # shape assertions are conditional on presence — coverage of a
            # missing card is requested_coverage's job, not sequence's
            return "skipped", "day %d: %r not on the day" % (day, want)
        positions.append(hits[0])
    if positions == sorted(positions):
        return "pass", "relative order holds: " + " → ".join(order)
    return "fail", "day %d order broken: %s (positions %s)" % (
        day,
        " → ".join(order),
        positions,
    )


def _eval_time_range(view: PlanView, args: dict, snapshot) -> tuple[str, str]:
    requires_pin = args.get("requires_pin")
    if requires_pin and not _has_pin(snapshot, requires_pin):
        return (
            "skipped",
            "scenario sets no pin for %r (timetable-fixed "
            "time only assertable with the pin)" % requires_pin,
        )
    day, name = int(args["day"]), str(args["name"])
    hits = [c for c in view.by_name(name) if c.day == day]
    if not hits:
        return "fail", "day %d: %r absent" % (day, name)
    card = hits[0]
    if not card.timed:
        return "fail", "day %d: %r untimed" % (day, name)
    lo, hi = hhmm_to_min(args["start"]), hhmm_to_min(args["end"])
    start = card.start_min or 0
    if lo <= start <= hi:
        return "pass", "%s starts %s within [%s, %s]" % (
            name,
            card.start,
            args["start"],
            args["end"],
        )
    return "fail", "%s starts %s outside [%s, %s]" % (
        name,
        card.start,
        args["start"],
        args["end"],
    )


def _eval_same_venue(view: PlanView, args: dict) -> tuple[str, str]:
    day, meal, name = int(args["day"]), str(args["meal"]), str(args["name"])
    meal_cards = [c for c in view.day_cards(day) if c.kind == "meal" and c.anchor]
    if not meal_cards:
        return "pending", "no meal cards in view (meal assembly F-31 lands in P1-F)"
    target = meal_cards[0]  # one lunch/dinner per day
    if target.anchor == name:
        return "pass", "%s on day %d anchored at %r" % (meal, day, name)
    return "fail", "%s on day %d anchored at %r, expected %r (B-03b')" % (
        meal,
        day,
        target.anchor,
        name,
    )


def _meal_bridges_arrival(
    view: PlanView, card: CardView, day: int, name: str, arrive: int
) -> bool:
    """F-22 same-venue meal bridges card start and leg arrival."""
    start = card.start_min or 0
    if view.engine == "cpsat":
        cid = getattr(card, "cid", None)
        return any(
            meal.get("day") == day
            and meal.get("host_cid") == cid
            and meal.get("start_min") == arrive
            and meal.get("end_min") == start
            for meal in view.meal_anchors
        )
    return any(
        meal.kind == "meal"
        and meal.anchor == name
        and meal.start_min == arrive
        and meal.end_min == start
        for meal in view.day_cards(day)
    )


def _eval_card_leg(view: PlanView, args: dict) -> tuple[str, str]:
    day, name = int(args["day"]), str(args["name"])
    hits = [c for c in view.by_name(name) if c.day == day]
    if not hits:
        return "fail", "day %d: %r absent" % (day, name)
    card = hits[0]
    if not card.timed:
        return "fail", "day %d: %r untimed (card ≡ leg untestable)" % (day, name)
    if view.engine == "cpsat":
        cid = getattr(card, "cid", None)
        legs = [
            leg
            for leg in view.access_legs
            if leg.get("cid") == cid and leg.get("day") == day
        ]
        if not legs:
            return "skipped", "no C-08 access leg recorded for %r" % name
        leg = legs[0]
        arrive = leg.get("arrive_poi_min")
        if arrive is not None and (card.start_min or 0) == arrive:
            return "pass", "visit start == leg arrival (%s)" % card.start
        if arrive is not None and _meal_bridges_arrival(view, card, day, name, arrive):
            return (
                "pass",
                "visit starts %s after the same-venue meal bridging leg "
                "arrival (%s)" % (card.start, min_to_hhmm(arrive)),
            )
        return "fail", "visit start %s != leg arrival %s" % (
            card.start,
            arrive,
        )
    leg = card.leg or {}
    arrive = hhmm_to_min(leg.get("arrive"))
    if arrive is None:
        return "skipped", "recording carries no leg times for %r" % name
    if (card.start_min or 0) == arrive:
        return "pass", "card start == leg arrive (%s)" % card.start
    if _meal_bridges_arrival(view, card, day, name, arrive):
        return (
            "pass",
            "card starts %s after the same-venue meal bridging leg arrive (%s)"
            % (card.start, leg.get("arrive")),
        )
    return "fail", "card start %s != leg arrive %s (B-03c)" % (
        card.start,
        leg.get("arrive"),
    )


def _eval_no_fill_before(view: PlanView, args: dict) -> tuple[str, str]:
    day, anchor = int(args["day"]), str(args["before"])
    cards = view.sorted_day(day)
    anchor_idx = next((i for i, c in enumerate(cards) if c.name == anchor), None)
    if anchor_idx is None:
        return (
            "skipped",
            "day %d: anchor %r not on the day (coverage is "
            "requested_coverage's job)" % (day, anchor),
        )
    fillers = [
        c.name
        for c in cards[:anchor_idx]
        if c.kind == KIND_VISIT and c.requested is False
    ]
    if not fillers:
        return "pass", "no unrequested visit before %r on day %d" % (anchor, day)
    return "fail", "unrequested before %r on day %d: %s (B-03a)" % (
        anchor,
        day,
        ", ".join(fillers),
    )


def _eval_requested_coverage(view: PlanView, args: dict, snapshot) -> tuple[str, str]:
    """Every must is timed OR in unplaced; an untimed requested card in
    days is the B-01 shape and always fails."""
    problems: list[str] = []
    for req in snapshot.request.musts:
        hits = view.by_name(req.name)
        timed = any(c.timed for c in hits)
        if timed:
            continue
        if hits and not any(c.timed for c in hits):
            problems.append("%r present but untimed (B-01 silent drop)" % req.name)
            continue
        if not any(u.get("name") == req.name for u in view.unplaced):
            problems.append("%r absent and not in unplaced" % req.name)
    if not problems:
        return "pass", "all %d musts timed or disclosed-unplaced" % len(
            snapshot.request.musts
        )
    return "fail", "; ".join(problems)


def _eval_no_cap_breach(
    view: PlanView, args: dict, ctx: "AssertContext"
) -> tuple[str, str]:
    checked: list[str] = []
    breaches: list[str] = []
    for card in view.cards:
        if card.kind != KIND_VISIT or not card.timed:
            continue
        cap_min: Optional[int] = None
        if (
            view.engine == "cpsat"
            and ctx.enriched is not None
            and getattr(card, "cid", None)
        ):
            cap, _reason = ctx.enriched.caps.get(card.cid, (None, "unknown"))
            cap_min = cap
        elif card.entry_cap:
            cap_min = hhmm_to_min(card.entry_cap)
        if cap_min is None:
            continue  # recording lacks caps → nothing asserted for that card
        checked.append(card.name)
        if (card.start_min or 0) > cap_min:
            breaches.append("%s starts %s past cap" % (card.name, card.start))
    if breaches:
        return "fail", "; ".join(breaches) + " (B-07 class)"
    if not checked:
        return "skipped", "no view carries entry-cap data for its cards"
    return "pass", "all %d cap-known cards start within cap" % len(checked)


def _eval_disclosure_contains(view: PlanView, args: dict) -> tuple[str, str]:
    key = str(args.get("key") or "")
    for line in view.disclosures:
        if key in line:
            return "pass", "disclosure contains %r" % key
    if view.engine == "cpsat":
        return (
            "pending",
            "disclosure templates (F-33) land in P1-F; %r not present yet" % key,
        )
    return "fail", "legacy disclosures lack %r" % key


def _eval_day_start_floor(view: PlanView, args: dict) -> tuple[str, str]:
    day = int(args["day"])
    floor = hhmm_to_min(args.get("not_before") or "00:00") or 0
    visits = view.timed_visits(day)
    if not visits:
        return "pass", "day %d has no timed visits (vacuous)" % day
    first = min(visits, key=lambda c: c.start_min or 0)
    if (first.start_min or 0) >= floor:
        return "pass", "first visit %s starts %s ≥ %s (C-05 arrival floor)" % (
            first.name,
            first.start,
            args.get("not_before"),
        )
    return "fail", "first visit %s starts %s < %s" % (
        first.name,
        first.start,
        args.get("not_before"),
    )


def _eval_day_end_ceiling(view: PlanView, args: dict) -> tuple[str, str]:
    day = int(args["day"])
    ceiling = hhmm_to_min(args.get("not_after") or "23:59")
    visits = view.timed_visits(day)
    if not visits:
        return "pass", "day %d has no timed visits (vacuous)" % day
    last = max(visits, key=lambda c: c.end_min or 0)
    if (last.end_min or 0) <= ceiling:
        return "pass", "last visit %s ends %s ≤ %s (C-05 departure buffer)" % (
            last.name,
            last.end,
            args.get("not_after"),
        )
    return "fail", "last visit %s ends %s > %s" % (
        last.name,
        last.end,
        args.get("not_after"),
    )


def _eval_remote_day_purity(view: PlanView, args: dict) -> tuple[str, str]:
    """C-06/C-15 shape: the day holding the named remote visit carries no
    unrequested visit (city fill on a remote day — B-08 family)."""
    name = str(args["name"])
    hits = [c for c in view.by_name(name) if c.timed]
    if not hits:
        return (
            "skipped",
            "%r not timed on any day (coverage is requested_coverage's job)" % name,
        )
    day = hits[0].day
    fillers = [
        c.name
        for c in view.day_cards(day)
        if c.kind == KIND_VISIT and c.requested is False and c.timed
    ]
    if fillers:
        return "fail", "day %d (remote %r) carries unrequested: %s (B-08/C-06)" % (
            day,
            name,
            ", ".join(fillers),
        )
    return "pass", "day %d holding remote %r carries no unrequested visit" % (day, name)


def _eval_span_cap(view: PlanView, args: dict) -> tuple[str, str]:
    """Q1 duration policy: a placed card may not span past the tier cap."""
    name = str(args["name"])
    max_min = int(args["max_minutes"])
    hits = view.by_name(name)
    if not hits:
        return "skipped", "%r absent (coverage is requested_coverage's job)" % name
    timed = [c for c in hits if c.timed]
    if not timed:
        return "fail", "%r present but untimed" % name
    card = timed[0]
    span = (card.end_min or 0) - (card.start_min or 0)
    if span <= max_min:
        return "pass", "%r span %d min ≤ %d" % (name, span, max_min)
    return "fail", "%r span %d min > %d (Q1 clamp)" % (name, span, max_min)


def _eval_city_coherence(view: PlanView, args: dict) -> tuple[str, str]:
    """C-07: no day mixes cities (cards must carry city data)."""
    per_day: dict[int, set[str]] = {}
    for card in view.cards:
        if card.kind != KIND_VISIT or not card.timed or not card.city:
            continue
        per_day.setdefault(card.day, set()).add(card.city)
    if not per_day:
        return "skipped", "no timed visit carries city data in this view"
    mixed = {d: sorted(cs) for d, cs in per_day.items() if len(cs) > 1}
    if mixed:
        return "fail", "days mixing cities (C-07): %s" % "; ".join(
            "day %d=%s" % (d, "/".join(cs)) for d, cs in sorted(mixed.items())
        )
    return "pass", "all %d city-known days are single-city" % len(per_day)


_EVALUATORS = {
    "sequence": lambda view, args, ctx: _eval_sequence(view, args),
    "time_range": lambda view, args, ctx: _eval_time_range(view, args, ctx.snapshot),
    "same_venue": lambda view, args, ctx: _eval_same_venue(view, args),
    "card_leg_consistent": lambda view, args, ctx: _eval_card_leg(view, args),
    "no_unrequested_before": lambda view, args, ctx: _eval_no_fill_before(view, args),
    "requested_coverage": lambda view, args, ctx: _eval_requested_coverage(
        view, args, ctx.snapshot
    ),
    "no_entry_cap_breach": lambda view, args, ctx: _eval_no_cap_breach(view, args, ctx),
    "disclosure_contains": lambda view, args, ctx: _eval_disclosure_contains(
        view, args
    ),
    "day_start_floor": lambda view, args, ctx: _eval_day_start_floor(view, args),
    "day_end_ceiling": lambda view, args, ctx: _eval_day_end_ceiling(view, args),
    "remote_day_purity": lambda view, args, ctx: _eval_remote_day_purity(view, args),
    "span_cap": lambda view, args, ctx: _eval_span_cap(view, args),
    "city_coherence": lambda view, args, ctx: _eval_city_coherence(view, args),
}


def evaluate(assertion: dict, view: PlanView, ctx: AssertContext) -> dict:
    """Evaluate one M7 assertion against one view. Unknown types fail loud
    (a silent pass on a typo'd type would corrupt the report)."""
    kind = str(assertion.get("type") or "")
    fn = _EVALUATORS.get(kind)
    if fn is None:
        return _result(
            "fail", assertion, view.engine, "unknown assertion type %r" % kind
        )
    try:
        status, detail = fn(view, assertion.get("args") or {}, ctx)
    except Exception as exc:  # a broken assertion is a report bug, not a plan bug
        return _result("fail", assertion, view.engine, "evaluator error: %r" % exc)
    return _result(status, assertion, view.engine, detail)
