"""PlanView — engine-neutral plan normalization (F-61 prerequisite, P2-A).

Both engines' outputs are normalized into the same shape so the diff
report compares like with like:

- `view_from_solution`  — the trip-level model (Solution → view). Pre-P1-F
  there are no *named* meal/hotel cards — C-09/F-22 meal intervals
  pass through as `meal_anchors` so card≡leg scans can see same-venue
  lunches; assertions that need restaurant detail still report
  `pending`, never a fake pass.
- `view_from_recording` — a recorded legacy run (committed JSON under
  tests/golden/legacy/, hand-encoded from incident dumps; audit M6
  "offline batch by default"). The recording carries the legacy engine's
  actual card times, unplaced and disclosures as observed.

A view is a value object; `signature(view)` is the canonical JSON used by
the determinism check (two runs byte-identical, F-41 instrument level).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from ..types import CandidateItem, FactSnapshot, Solution

# card kinds
KIND_VISIT = "visit"
KIND_MEAL = "meal"
KIND_HOTEL = "hotel"


def min_to_hhmm(minutes: Optional[int]) -> Optional[str]:
    if minutes is None:
        return None
    minutes = max(0, min(int(minutes), 24 * 60))
    return "%02d:%02d" % (minutes // 60, minutes % 60)


def hhmm_to_min(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    hh, mm = str(text).split(":")
    return int(hh) * 60 + int(mm)


@dataclass
class CardView:
    """One normalized card. `start=None` = untimed (the B-01 trigger)."""

    name: str
    day: int
    start: Optional[str] = None  # HH:MM or None
    end: Optional[str] = None
    kind: str = KIND_VISIT
    requested: Optional[bool] = None  # True/False/None=unknown (hotel/meal)
    poi_id: Optional[str] = None
    cid: Optional[str] = None  # model-side candidate id (cap/leg lookup)
    remote: bool = False
    city: Optional[str] = None  # candidate city (C-07 coherence)
    anchor: Optional[str] = None  # meal anchor (same_venue check)
    leg: Optional[dict] = None  # access-leg detail {board, arrive} if known
    entry_cap: Optional[str] = None  # legacy recordings may carry it
    meta: dict = field(default_factory=dict)

    @property
    def timed(self) -> bool:
        return self.start is not None

    @property
    def start_min(self) -> Optional[int]:
        return hhmm_to_min(self.start)

    @property
    def end_min(self) -> Optional[int]:
        return hhmm_to_min(self.end)


@dataclass
class PlanView:
    engine: str  # "cpsat" | "legacy"
    status: Optional[str] = None  # OPTIMAL/FEASIBLE/INFEASIBLE (model) / None
    cards: list[CardView] = field(default_factory=list)
    unplaced: list[dict] = field(default_factory=list)
    disclosures: list[str] = field(default_factory=list)
    access_legs: list[dict] = field(default_factory=list)  # model: C-08 legs
    meal_anchors: list[dict] = field(default_factory=list)  # model: C-09/F-22
    wall_ms: Optional[int] = None
    # R13d：引擎段墙钟（build+solve+ladder，enrich 属数据准备不计——
    # 引擎预算契约覆盖建模+求解，注释见 solve.py Q3 段）。
    engine_ms: Optional[int] = None
    # R13g：墙帽污染（Solution.wall_capped 透传）——影子层据此改判
    # 确定性对照（无墙压对），F-41 不测机器负载。
    wall_capped: bool = False

    def day_cards(self, day: int) -> list[CardView]:
        return [c for c in self.cards if c.day == day]

    def by_name(self, name: str) -> list[CardView]:
        return [c for c in self.cards if c.name == name]

    def timed_visits(self, day: int | None = None) -> list[CardView]:
        cards = self.cards if day is None else self.day_cards(day)
        return [c for c in cards if c.kind == KIND_VISIT and c.timed]

    def sorted_day(self, day: int) -> list[CardView]:
        """Day cards in start order; untimed cards sort last, stable."""
        return sorted(
            self.day_cards(day),
            key=lambda c: (c.start_min is None, c.start_min or 0),
        )


def view_from_solution(solution: Solution, snapshot: FactSnapshot) -> PlanView:
    """Normalize the model's Solution. An untimed requested card cannot be
    produced here by construction (SolutionItem always carries minutes) —
    the violation scan on this view is a regression guard, not a formality."""
    cand_by_cid: dict[str, CandidateItem] = {c.cid: c for c in snapshot.candidates}
    cards: list[CardView] = []
    for item in solution.items:
        cand = cand_by_cid.get(item.cid)
        cards.append(
            CardView(
                name=cand.name if cand else item.cid,
                day=item.day,
                start=min_to_hhmm(item.start_min),
                end=min_to_hhmm(item.end_min),
                kind=KIND_VISIT,
                requested=bool(cand.kind == "requested") if cand else None,
                poi_id=cand.poi_id if cand else None,
                cid=item.cid,
                remote=bool(cand.remote) if cand else False,
                city=cand.city if cand else None,
            )
        )
    return PlanView(
        engine="cpsat",
        status=solution.status,
        cards=cards,
        unplaced=list(solution.unplaced),
        disclosures=list(solution.disclosures),
        access_legs=list(solution.access_legs),
        meal_anchors=list(solution.meal_anchors),
        wall_ms=solution.wall_ms,
        wall_capped=bool(getattr(solution, "wall_capped", False)),
    )


def view_from_recording(raw: dict[str, Any]) -> PlanView:
    """Normalize a recorded legacy run (tests/golden/legacy/*.json).

    Recording schema (documented in tests/golden/legacy/README.md):
    {"days": [{"day": n, "items": [{name, start, end, kind, requested,
     remote, anchor, leg{board,arrive}, entry_cap}]}],
     "unplaced": [{rid,name,reason}...], "disclosures": [str...]}
    """
    cards: list[CardView] = []
    for day in raw.get("days", ()):
        day_no = int(day.get("day") or 0)
        for item in day.get("items", ()):
            leg = item.get("leg") or None
            cards.append(
                CardView(
                    name=str(item.get("name") or ""),
                    day=day_no,
                    start=item.get("start"),
                    end=item.get("end"),
                    kind=str(item.get("kind") or KIND_VISIT),
                    requested=(
                        bool(item["requested"])
                        if item.get("requested") is not None
                        else None
                    ),
                    poi_id=item.get("poi_id"),
                    remote=bool(item.get("remote", False)),
                    city=item.get("city"),
                    anchor=item.get("anchor"),
                    leg=leg,
                    entry_cap=item.get("entry_cap"),
                )
            )
    return PlanView(
        engine="legacy",
        status=raw.get("status"),
        cards=cards,
        unplaced=list(raw.get("unplaced", ())),
        disclosures=[str(d) for d in raw.get("disclosures", ())],
    )


def signature(view: PlanView) -> str:
    """Canonical JSON of a view — determinism comparison key (F-41)."""
    payload = {
        "engine": view.engine,
        "status": view.status,
        "cards": [
            {
                "name": c.name,
                "day": c.day,
                "start": c.start,
                "end": c.end,
                "kind": c.kind,
                "requested": c.requested,
            }
            for c in sorted(
                view.cards,
                key=lambda c: (c.day, c.start_min is None, c.start_min or 0, c.name),
            )
        ],
        "unplaced": sorted((u.get("rid"), u.get("name")) for u in view.unplaced),
        "meal_anchors": sorted(
            (
                m.get("slot"),
                m.get("day"),
                m.get("start_min"),
                m.get("end_min"),
                m.get("host_cid"),
            )
            for m in view.meal_anchors
        ),
        "disclosures": sorted(view.disclosures),
    }
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
