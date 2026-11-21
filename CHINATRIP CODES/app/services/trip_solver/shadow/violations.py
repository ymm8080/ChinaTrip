"""Bug-class violation scan on any PlanView (F-61 relative criteria, P2-A).

These are the classes the global model must eliminate by construction —
B-01 / B-02 / B-03a / B-03c / B-06 (cpsat_as_is §4). The scan runs on the
legacy recording (where the incident's violations must be *detected* —
proof the instrument works) and on the model solution (where the P3 gate
requires zero). Scanning is structural, no heuristics: each detector names
its evidence.

Conservative by design (documented in each detector): a detector may
over-approximate "seatable" (B-02) but never under-approximate a violation
class — the relative criterion is "not worse", so false-positive-ish
conservatism is safe; false negatives would corrupt the gate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .views import KIND_MEAL, KIND_VISIT, CardView, PlanView

if TYPE_CHECKING:  # pragma: no cover
    from .asserts import AssertContext


def _requested_unseated(view: PlanView, snapshot) -> list[str]:
    """Requested musts that are neither timed anywhere nor present-and-timed."""
    out: list[str] = []
    for req in snapshot.request.musts:
        hits = view.by_name(req.name)
        if hits and any(c.timed for c in hits):
            continue
        if not hits and any(u.get("name") == req.name for u in view.unplaced):
            continue  # honestly unplaced — not "unseated while seating fills"
        # present-but-untimed (B-01 shape) or absent-without-unplaced-row
        out.append(req.name)
    return out


def scan_b01_silent_drop(view: PlanView, ctx: "AssertContext") -> list[dict]:
    """Requested card present in days but untimed; and (the incident's full
    shape) NOT in unplaced → the UI strips it and the user sees nothing."""
    out: list[dict] = []
    for card in view.cards:
        if card.kind != KIND_VISIT or card.requested is not True or card.timed:
            continue
        disclosed = any(u.get("name") == card.name for u in view.unplaced)
        out.append(
            {
                "bug": "B-01",
                "day": card.day,
                "evidence": "%r present untimed%s"
                % (
                    card.name,
                    "" if disclosed else " and not in unplaced (silent)",
                ),
            }
        )
    return out


def scan_b02_fill_over_must(view: PlanView, ctx: "AssertContext") -> list[dict]:
    """A timed unrequested visit on a day while a must is unseated anywhere."""
    unseated = _requested_unseated(view, ctx.snapshot)
    if not unseated:
        return []
    out: list[dict] = []
    for card in view.cards:
        if card.kind != KIND_VISIT or card.requested is not False or not card.timed:
            continue
        out.append(
            {
                "bug": "B-02",
                "day": card.day,
                "evidence": "unrequested %r holds %s while unseated: %s"
                % (
                    card.name,
                    card.start,
                    ", ".join(unseated),
                ),
            }
        )
    return out


def scan_b03a_fill_before_remote(view: PlanView, ctx: "AssertContext") -> list[dict]:
    """On a remote day, an unrequested visit strictly before the remote
    visit's outbound (card start ≤ remote card start ⇒ before departure)."""
    out: list[dict] = []
    for remote in view.cards:
        if not (remote.kind == KIND_VISIT and remote.remote and remote.timed):
            continue
        for card in view.sorted_day(remote.day):
            if card is remote:
                break  # stop at the remote card — only *before* counts
            if card.kind == KIND_VISIT and card.requested is False and card.timed:
                out.append(
                    {
                        "bug": "B-03a",
                        "day": remote.day,
                        "evidence": "unrequested %r (%s) precedes remote %r (%s)"
                        % (
                            card.name,
                            card.start,
                            remote.name,
                            remote.start,
                        ),
                    }
                )
    return out


def _cpsat_meal_bridges_arrival(view: PlanView, card: CardView, arrive: int) -> bool:
    """F-22 same-venue meal: the remote site hosts the meal and the meal
    spans [leg arrival, visit start] — card = arrival + meal, not a
    mismatch. Any other gap (or a meal hosted elsewhere) stays flagged."""
    start = card.start_min or 0
    for meal in view.meal_anchors:
        if meal.get("day") != card.day or meal.get("host_cid") != card.cid:
            continue
        if meal.get("start_min") == arrive and meal.get("end_min") == start:
            return True
    return False


def _legacy_meal_bridges_arrival(
    view: PlanView, card: CardView, arrive_min: int
) -> bool:
    start = card.start_min or 0
    for meal in view.day_cards(card.day):
        if meal.kind != KIND_MEAL or meal.anchor != card.name:
            continue
        if meal.start_min == arrive_min and meal.end_min == start:
            return True
    return False


def scan_b03c_card_leg_mismatch(view: PlanView, ctx: "AssertContext") -> list[dict]:
    """Remote card start ≠ its access-leg arrival — the two were computed
    by different passes (legacy) or the invariant regressed (model).
    Exception (F-22, 2026-11-18 ruling): a remote arrival in 11:00–13:00
    may seat the same-venue lunch first; the visit then starts at the
    meal's end. A meal anchored elsewhere (the 24379abd incident: city
    lunch while the card claimed the shuttle's arrival) is still a
    mismatch."""
    out: list[dict] = []
    for card in view.cards:
        if not (card.kind == KIND_VISIT and card.remote and card.timed):
            continue
        if view.engine == "cpsat":
            legs = [
                leg
                for leg in view.access_legs
                if leg.get("cid") == card.cid and leg.get("day") == card.day
            ]
            if not legs:
                continue
            arrive = legs[0].get("arrive_poi_min")
            if arrive is None or (card.start_min or 0) == arrive:
                continue
            if _cpsat_meal_bridges_arrival(view, card, arrive):
                continue
            out.append(
                {
                    "bug": "B-03c",
                    "day": card.day,
                    "evidence": "%r card %s ≠ leg arrival %d min"
                    % (
                        card.name,
                        card.start,
                        arrive,
                    ),
                }
            )
        else:
            arrive = (card.leg or {}).get("arrive")
            if not arrive:
                continue
            from .views import hhmm_to_min

            arrive_min = hhmm_to_min(arrive)
            if (card.start_min or 0) == arrive_min:
                continue
            if _legacy_meal_bridges_arrival(view, card, arrive_min):
                continue
            out.append(
                {
                    "bug": "B-03c",
                    "day": card.day,
                    "evidence": "%r card %s ≠ leg arrive %s"
                    % (
                        card.name,
                        card.start,
                        arrive,
                    ),
                }
            )
    return out


def scan_b06_double_presence(view: PlanView, ctx: "AssertContext") -> list[dict]:
    """Same site both timed in days and listed unplaced."""
    out: list[dict] = []
    timed_names = {c.name for c in view.cards if c.kind == KIND_VISIT and c.timed}
    for u in view.unplaced:
        name = u.get("name")
        if name and name in timed_names:
            out.append(
                {
                    "bug": "B-06",
                    "day": None,
                    "evidence": "%r timed in days AND in unplaced" % name,
                }
            )
    return out


_SCANNERS = (
    scan_b01_silent_drop,
    scan_b02_fill_over_must,
    scan_b03a_fill_before_remote,
    scan_b03c_card_leg_mismatch,
    scan_b06_double_presence,
)


def scan_violations(view: PlanView, ctx: "AssertContext") -> list[dict]:
    """Run every B-class detector; returns a stable-ordered evidence list."""
    out: list[dict] = []
    for scanner in _SCANNERS:
        out.extend(scanner(view, ctx))
    out.sort(key=lambda v: (v["bug"], v.get("day") is None, v.get("day") or 0))
    return out


def violation_counts(violations: list[dict]) -> dict[str, int]:
    counts = {"B-01": 0, "B-02": 0, "B-03a": 0, "B-03c": 0, "B-06": 0}
    for v in violations:
        counts[v["bug"]] = counts.get(v["bug"], 0) + 1
    return counts
