"""Tests for app/services/itinerary_store.py (§5.4, iron rule 16, §6.8)."""

from datetime import time

import pytest

from app.services.entitlement import (
    EntitlementService,
    InMemoryQuotaStore,
)
from app.services.itinerary import DiffOp, PoiHours, VisitItem
from app.services.itinerary_store import (
    InMemoryItineraryStore,
    ItineraryService,
    QuotaExceededError,
)


def make_service() -> tuple[InMemoryItineraryStore, ItineraryService]:
    store = InMemoryItineraryStore()
    return store, ItineraryService(store)


def make_entitlement(snapshot_limit: int = 3) -> EntitlementService:
    return EntitlementService(
        InMemoryQuotaStore(), rules=[], quotas={"snapshot_limit": snapshot_limit}
    )


def visit(
    item_id: str,
    *,
    day: int = 1,
    start: time = time(10, 0),
    duration: int = 120,
    city: str = "北京",
    poi_id: str | None = None,
) -> VisitItem:
    return VisitItem(
        item_id=item_id,
        name=f"景点{item_id}",
        city=city,
        day=day,
        start_time=start,
        duration_minutes=duration,
        poi_id=poi_id,
    )


def add_op(v: VisitItem) -> DiffOp:
    return DiffOp(op="add", item=v)


# --- create ------------------------------------------------------------------


def test_create_starts_from_empty_plan_at_version_1():
    store, service = make_service()
    record = service.create("device-a", ["北京", "上海"])
    assert record.working_sync_version == 1
    assert record.owner_device_id == "device-a"
    assert record.plan.cities == ["北京", "上海"]
    assert record.plan.days == []
    assert record.snapshots == []
    assert store.get(record.itinerary_id) is record
    assert store.list_by_owner("device-a") == [record]
    assert store.list_by_owner("device-b") == []


def test_create_with_days_count_builds_empty_day_plans():
    _store, service = make_service()
    record = service.create("device-a", ["北京"], days_count=3)
    assert [d.day for d in record.plan.days] == [1, 2, 3]
    assert all(d.base_city == "北京" for d in record.plan.days)
    assert all(d.items == [] for d in record.plan.days)


# --- mutate + version bump -----------------------------------------------------


def test_mutate_success_bumps_working_sync_version():
    _store, service = make_service()
    record = service.create("device-a", ["北京"], days_count=2)
    record, report, summary = service.mutate(record, [add_op(visit("a"))])
    assert report.ok
    assert record.working_sync_version == 2
    assert record.plan.days[0].items[0].item_id == "a"
    assert summary.affected_items_count == 1


def test_mutate_error_violation_leaves_version_and_plan_untouched():
    _store, service = make_service()
    record = service.create("device-a", ["北京"], days_count=1)
    # Iron rule 2: visit starts before the POI opens -> error severity.
    bad = visit("bad", start=time(8, 0), duration=60, poi_id="p1")
    hours = [PoiHours(poi_id="p1", opens=time(10, 0), closes=time(18, 0))]
    record, report, _summary = service.mutate(record, [add_op(bad)], poi_hours=hours)
    assert not report.ok
    assert any(v.rule_id == 2 for v in report.violations)
    assert record.working_sync_version == 1  # version frozen on failure
    assert record.plan.days[0].items == []  # working copy untouched


# --- snapshots -----------------------------------------------------------------


def test_snapshot_freezes_working_copy_and_auto_names():
    _store, service = make_service()
    record = service.create("device-a", ["北京"], days_count=1)
    record, _, _ = service.mutate(record, [add_op(visit("a"))])
    snap1 = service.create_snapshot(
        record, entitlement=make_entitlement(), subject_id="device-a"
    )
    assert snap1.name == "v1"
    assert snap1.sync_version == record.working_sync_version == 2
    assert snap1.plan is not record.plan  # deep copy, not a reference

    # Later mutations must not leak into the frozen snapshot.
    record, _, _ = service.mutate(record, [add_op(visit("b", start=time(14, 0)))])
    assert [i.item_id for i in snap1.plan.days[0].items] == ["a"]
    snap2 = service.create_snapshot(
        record,
        name="改完这版",
        note="before flight",
        entitlement=make_entitlement(),
        subject_id="device-a",
    )
    assert snap2.name == "改完这版"
    assert snap2.note == "before flight"
    assert snap2.name != "v2"  # explicit name wins
    assert [s.name for s in record.snapshots] == ["v1", "改完这版"]


def test_restore_writes_only_working_copy_and_keeps_snapshot_immutable():
    _store, service = make_service()
    record = service.create("device-a", ["北京"], days_count=1)
    record, _, _ = service.mutate(record, [add_op(visit("a"))])
    snap = service.create_snapshot(
        record, entitlement=make_entitlement(), subject_id="device-a"
    )
    frozen = snap.model_copy(deep=True)  # reference for immutability check

    record, _, _ = service.mutate(record, [add_op(visit("b", start=time(14, 0)))])
    assert record.working_sync_version == 3

    record = service.restore(record, snap.snapshot_id)
    # Working copy = snapshot plan (deep copy), version +1, active set.
    assert record.working_sync_version == 4
    assert record.active_snapshot_id == snap.snapshot_id
    assert [i.item_id for i in record.plan.days[0].items] == ["a"]
    assert record.plan is not snap.plan
    # Iron rule 16: the snapshot itself is byte-identical after restore.
    assert snap == frozen

    # Post-restore mutation must not reach back into the snapshot either.
    record, _, _ = service.mutate(record, [add_op(visit("c", start=time(16, 0)))])
    assert snap == frozen


def test_restore_unknown_snapshot_raises_keyerror():
    _store, service = make_service()
    record = service.create("device-a", ["北京"])
    with pytest.raises(KeyError):
        service.restore(record, "snap_missing")


def test_snapshot_quota_denied_raises_with_paywall_trigger():
    _store, service = make_service()
    record = service.create("device-a", ["北京"])
    entitlement = make_entitlement(snapshot_limit=1)
    snap = service.create_snapshot(
        record, entitlement=entitlement, subject_id="device-a"
    )
    assert snap.name == "v1"
    with pytest.raises(QuotaExceededError) as excinfo:
        service.create_snapshot(record, entitlement=entitlement, subject_id="device-a")
    assert excinfo.value.paywall_trigger == "snapshot_limit_hit"
    assert excinfo.value.denied_reason == "quota_exhausted"
    assert len(record.snapshots) == 1  # denied attempt appended nothing


# --- store semantics ------------------------------------------------------------


def test_put_upsert_and_delete():
    store = InMemoryItineraryStore()
    assert store.delete("nope") is False
    assert store.new_itinerary_id() != store.new_itinerary_id()
    record = ItineraryService(store).create("device-a", ["北京"])
    record.plan.cities.append("上海")
    store.put(record)  # upsert replaces
    assert store.get(record.itinerary_id).plan.cities == ["北京", "上海"]
    assert store.delete(record.itinerary_id) is True
    assert store.get(record.itinerary_id) is None
