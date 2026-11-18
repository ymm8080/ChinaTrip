"""F-61 legacy side, P2-B: in-process cascade replay + determinism calibration.

Replays a committed corpus snapshot through the REAL legacy cascade
(``app.services.agent.plan.PlanningAgent._generate_v0``) with every I/O
stubbed from the snapshot itself (audit M6 offline-batch):

- the POI store serves exactly the snapshot's candidates — both engines
  see the same pool, apples to apples;
- the weather lookup maps snapshot weather rows (bilingual text so the
  legacy 雨 scan and the F-13 ``rain`` scan both recognise it);
- the LLM is a boom sentinel — algorithm mode is the default path and any
  LLM call is a replay bug, surfaced as a failed recording, never hidden;
- trains/flights are the deterministic mocks the agent itself defaults to.

Each replay runs twice on a fresh agent; the recording's provenance carries
``kind: "in-process-replay"``, ``runs`` and ``determinism`` (byte-identical
signatures) — the calibration the shadow report's legacy-side
``deterministic`` assertion consumes. ``auto_restaurants`` stays off for
v1: meal-card fidelity and access-leg capture are the next P2-B iteration;
recordings say so in provenance and meal/leg assertions pend honestly.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
from typing import TYPE_CHECKING, Optional

from app.services.poi_details import PoiDetailStore

from .corpus import Scenario, load_corpus
from .views import signature, view_from_recording

if TYPE_CHECKING:  # pragma: no cover
    from ..types import CandidateItem, FactSnapshot

REPLAY_DEVICE = "shadow-replay"
_WEATHER_TEXT = {
    "light rain": "小雨 (light rain)",
    "heavy rain": "大雨 (heavy rain)",
}


class _BoomLLM:
    """Algorithm mode must not touch the LLM — any call is a replay bug."""

    name = "boom-sentinel"

    async def chat(self, messages, *, temperature: float = 0.3, max_tokens=None):
        raise AssertionError(
            "legacy replay hit the LLM — algorithm mode must stay zero-LLM"
        )


def _norm_city(city: str | None) -> str:
    return (city or "").strip().removesuffix("市")


class SnapshotStore(PoiDetailStore):
    """PoiDetailStore stand-in serving exactly the snapshot's candidates.

    Shaped like the real store's row dicts (``top_pois_in_city`` /
    ``search_keyword`` shape): location is a (lon, lat) tuple, ``_tier``
    carries the snapshot tier, everything else maps 1:1. Unoverridden
    helpers keep the base store's in-memory (no-DB) behaviour.
    Deterministic: snapshot order is preserved everywhere.
    """

    def __init__(self, candidates) -> None:
        super().__init__()
        self._rows: list[dict] = [_row_from(c) for c in candidates]

    # -- store interface -----------------------------------------------------
    def _city_rows(self, city: str | None) -> list[dict]:
        if city is None:
            return list(self._rows)
        want = _norm_city(city)
        return [r for r in self._rows if _norm_city(r.get("city")) == want]

    def top_pois_in_city(
        self, city: str, limit: int = 30, *, exclude_food: bool = True
    ):
        rows = self._city_rows(city)
        if exclude_food:
            rows = [r for r in rows if (r.get("category") or "") != "food"]
        return rows[:limit]

    def match_text_names(self, city, text, *, limit: int = 8):
        probe = (text or "").strip()
        if not probe:
            return []
        hits = [
            r
            for r in self._city_rows(city)
            if r.get("name") and (r["name"] in probe or probe in r["name"])
        ]
        return hits[:limit]

    def candidate_by_name(self, city, name):
        want = (name or "").strip()
        for r in self._city_rows(city):
            if (r.get("name") or "").strip() == want:
                return dict(r)
        return None

    def search_keyword(self, city, tokens, *, limit: int = 5):
        toks = [t for t in (tokens or []) if t]
        if not toks:
            return []
        hits = []
        for r in self._city_rows(city):
            hay = "%s %s" % (r.get("name") or "", r.get("category") or "")
            if any(t in hay for t in toks):
                hits.append(r)
        return hits[:limit]


def _row_from(cand: "CandidateItem") -> dict:
    location = (
        (float(cand.lon), float(cand.lat))
        if cand.lon is not None and cand.lat is not None
        else None
    )
    return {
        "id": cand.poi_id or cand.cid,
        "name": cand.name,
        "city": cand.city,
        "category": cand.category,
        "location": location,
        "opening_hours": cand.opening_hours,
        "best_visit_time": cand.best_visit_time,
        "suggested_duration_min": cand.suggested_duration_min,
        "indoor": cand.indoor,
        "rain_ok": cand.rain_ok,
        "tags": [],
        "source": "shadow-replay",
        "rating": cand.quality,
        "rating_count": 0,
        "_tier": cand.tier if cand.tier is not None else 10,
        "status": "active",
    }


def _weather_lookup_factory(snapshot: "FactSnapshot"):
    """(city, date_iso) → (day_text, night_text) windows, from the snapshot's
    weather rows — the legacy ``_rain_map`` unpacks the two-window tuple
    (production injects ``weather.daily_weather_text`` 双窗); the bilingual
    text keeps both the legacy 雨 scan and the F-13 ``rain`` scan working."""
    poi_city = {c.poi_id: c.city for c in snapshot.candidates if c.poi_id and c.city}
    by_day: dict[tuple[str, str], str] = {}
    for poi_id, day_iso, cond in snapshot.weather or ():
        city = poi_city.get(poi_id)
        if not city or not cond:
            continue
        text = _WEATHER_TEXT.get(str(cond).strip(), str(cond))
        by_day[(_norm_city(city), day_iso)] = text

    def lookup(city: str, date_iso: str):
        text = by_day.get((_norm_city(city), date_iso))
        return (text, text) if text else None

    return lookup


def _t2s(value) -> Optional[str]:
    if value is None:
        return None
    return "%02d:%02d" % (value.hour, value.minute)


async def replay_scenario(scenario: Scenario) -> dict:
    """Run the legacy cascade once on the scenario snapshot → recording."""
    from app.services.agent.plan import PlanningAgent, PlanSession

    store = SnapshotStore(scenario.snapshot.candidates)
    agent = PlanningAgent(
        _BoomLLM(),
        amap_client=None,
        poi_details=store,
        auto_restaurants=False,
        weather_lookup=_weather_lookup_factory(scenario.snapshot),
    )
    req = scenario.snapshot.request
    session = PlanSession(
        session_id="shadow-replay-%s" % scenario.name,
        device_id=REPLAY_DEVICE,
        cities=list(req.cities),
        days=req.days,
        start_date=req.start_date,
        arrival_time=req.arrival_time,
        departure_time=req.departure_time,
        must_visits=[m.name for m in req.musts],
    )
    session = await agent._generate_v0(session)
    return _recording_from_session(scenario, session)


def _recording_from_session(scenario: Scenario, session) -> dict:
    from app.services.itinerary.models import VisitItem

    must_names = [m.name for m in scenario.snapshot.request.musts]
    days: list[dict] = []
    plan = getattr(session, "plan", None)
    if plan is not None:
        for day in plan.days:
            items = []
            for item in day.items:
                if not isinstance(item, VisitItem):
                    continue  # transfer legs: capture pends next P2-B iteration
                is_hotel = (item.category or "") == "hotel" or item.name.startswith(
                    "🏨"
                )
                kind = (
                    "hotel"
                    if is_hotel
                    else ("meal" if (item.category or "") == "food" else "visit")
                )
                items.append(
                    {
                        "name": item.name,
                        "start": _t2s(item.start_time),
                        "end": _t2s(item.end_time),
                        "kind": kind,
                        # must → True; non-must visits → False (the B-02/B-03a
                        # scans key on requested is False); structure cards
                        # (hotel) stay None — they are neither
                        "requested": (None if is_hotel else item.name in must_names),
                        "remote": bool(getattr(item, "remote", False)),
                        "city": item.city,
                        "poi_id": item.poi_id,
                    }
                )
            days.append({"day": day.day, "items": items})
    timed_names = {i["name"] for d in days for i in d["items"] if i.get("start")}
    unplaced: list[dict] = []
    for m in scenario.snapshot.request.musts:
        if m.name in timed_names:
            continue
        reason = next(
            (a for a in (session.assumptions or []) if m.name in str(a)),
            None,
        )
        unplaced.append(
            {"rid": m.rid, "name": m.name, "reason": reason or "absent-from-plan"}
        )
    return {
        "schema_version": 1,
        "engine": "legacy",
        "kind": "in-process-replay",
        "provenance": {
            "source": os.path.basename(scenario.path),
            "replayed_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "auto_restaurants": False,
            "llm": "boom-sentinel",
            "note": "in-process cascade replay (P2-B): store/weather/llm "
            "stubbed from the snapshot; meal cards, access legs and user "
            "pins are not captured this iteration — pin-shaped assertions "
            "fail honestly on this side rather than faking a pass",
        },
        "days": days,
        "unplaced": unplaced,
        "disclosures": [str(a) for a in (session.assumptions or [])],
    }


def replay_scenario_sync(scenario: Scenario) -> dict:
    return asyncio.run(replay_scenario(scenario))


def replay_corpus(
    corpus_dir: Optional[str] = None, *, force: bool = False, runs: int = 2
) -> dict:
    """Regenerate legacy recordings for the corpus (missing ones by default).

    Hand recordings (kind recorded-actual-output) are never overwritten —
    they are incident ground truth. Existing in-process-replay recordings
    refresh only with force.
    """
    summary: dict = {"written": [], "kept": [], "failed": []}
    for scenario in load_corpus(corpus_dir):
        out = os.path.join(
            os.path.dirname(scenario.path), "legacy", "%s_legacy.json" % scenario.name
        )
        if os.path.exists(out):
            try:
                with open(out, "r", encoding="utf-8") as fh:
                    existing = json.load(fh)
                kind = existing.get("kind") or (
                    (existing.get("provenance") or {}).get("kind")
                )
            except (OSError, ValueError):
                kind = None
            if kind != "in-process-replay" or not force:
                summary["kept"].append(scenario.name)
                continue
        try:
            recs = [replay_scenario_sync(scenario) for _ in range(runs)]
        except Exception as exc:  # a failed replay is a finding, not a crash
            summary["failed"].append({"name": scenario.name, "error": repr(exc)})
            continue
        deterministic = signature(view_from_recording(recs[0])) == signature(
            view_from_recording(recs[1])
        )
        recs[0]["provenance"]["runs"] = runs
        recs[0]["provenance"]["determinism"] = deterministic
        blob = json.dumps(recs[0], ensure_ascii=False, indent=1)
        banned = ("session_id", "account_id", "@qq.com", "shadow-replay")
        leaked = [b for b in banned if b in blob]
        if leaked:
            summary["failed"].append(
                {"name": scenario.name, "error": "anonymization: %s" % leaked}
            )
            continue
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(blob + "\n")
        summary["written"].append(
            {"name": scenario.name, "deterministic": deterministic}
        )
    return summary


if __name__ == "__main__":  # pragma: no cover
    import sys

    result = replay_corpus(force="--force" in sys.argv)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    sys.exit(0 if not result["failed"] else 1)
