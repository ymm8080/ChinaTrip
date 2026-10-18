# -*- coding: utf-8 -*-
"""state_persist: sessions and itineraries survive a process restart
(the dev workflow restarts uvicorn on every code change)."""

from app.services.agent.plan import PlanSession
from app.services.itinerary.models import DayPlan, ItineraryPlan
from app.services.itinerary_store import ItineraryRecord
from app.services.state_persist import (
    PersistentItineraryStore,
    PersistentPlanSessionStore,
    SqliteStateBackend,
)


def _backend(tmp_path):
    return SqliteStateBackend(str(tmp_path / "h5_state.db"))


def _session(sid="s1", device="d1", state="ready"):
    return PlanSession(
        session_id=sid,
        device_id=device,
        cities=["厦门", "重庆"],
        days=4,
        state=state,
    )


def _plan(iid="it-p1"):
    return ItineraryPlan(
        itinerary_id=iid,
        cities=["厦门"],
        days=[DayPlan(day=1, base_city="厦门", items=[])],
        assumptions=["a1"],
    )


def test_sessions_survive_store_reinstantiation(tmp_path):
    backend = _backend(tmp_path)
    store1 = PersistentPlanSessionStore(backend)
    session = _session()
    store1.save(session)

    store2 = PersistentPlanSessionStore(backend)  # "restarted process"
    loaded = store2.get("s1", device_id="d1")
    assert loaded is not None
    assert loaded.cities == ["厦门", "重庆"]
    assert loaded.days == 4
    # device scoping still enforced after reload
    assert store2.get("s1", device_id="other") is None


def test_itineraries_roundtrip_and_delete_honored_on_disk(tmp_path):
    backend = _backend(tmp_path)
    store1 = PersistentItineraryStore(backend)
    record = ItineraryRecord(
        itinerary_id="it-p1", owner_device_id="d1", plan=_plan()
    )
    store1.put(record)

    store2 = PersistentItineraryStore(backend)
    assert store2.get("it-p1") is not None
    assert [r.itinerary_id for r in store2.list_by_owner("d1")] == ["it-p1"]

    assert store2.delete("it-p1") is True
    store3 = PersistentItineraryStore(backend)
    assert store3.get("it-p1") is None


def test_corrupt_rows_are_skipped_not_fatal(tmp_path):
    backend = _backend(tmp_path)
    backend.save_session("bad", "{not json")
    backend.save_itinerary("bad-it", "{not json")
    backend.save_session("good", _session(sid="good").model_dump_json())

    sessions = PersistentPlanSessionStore(backend)
    itineraries = PersistentItineraryStore(backend)
    assert sessions.get("good", device_id="d1") is not None
    assert sessions.get("bad", device_id="d1") is None
    assert itineraries.get("bad-it") is None
