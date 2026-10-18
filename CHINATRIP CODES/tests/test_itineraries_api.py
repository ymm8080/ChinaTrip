"""Tests for the /api/v1/itineraries routes (design v2.0 §5.4/§6.8).

App assembly mirrors tests/test_translate_api.py: fresh store + entitlement
per app via dependency_overrides, so quota counters never leak across tests.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.itineraries import (
    get_entitlement_service,
    get_store,
)
from app.api.itineraries import (
    router as itineraries_router,
)
from app.services.entitlement import EntitlementService, InMemoryQuotaStore
from app.services.itinerary_store import InMemoryItineraryStore

DEV_A = {"X-Device-ID": "device-a"}
DEV_B = {"X-Device-ID": "device-b"}


def make_app(*, snapshot_limit: int = 3) -> TestClient:
    store = InMemoryItineraryStore()
    entitlement = EntitlementService(
        InMemoryQuotaStore(), rules=[], quotas={"snapshot_limit": snapshot_limit}
    )
    app = FastAPI()
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_entitlement_service] = lambda: entitlement
    app.include_router(itineraries_router)
    return TestClient(app)


def create_itinerary(client: TestClient, headers=DEV_A, **body) -> dict:
    payload = {"cities": ["北京"], "days": 2, **body}
    resp = client.post("/api/v1/itineraries", json=payload, headers=headers)
    assert resp.status_code == 201
    return resp.json()


def add_diff(item_id: str, *, start="10:00", duration=120, day=1, poi_id=None) -> dict:
    return {
        "op": "add",
        "item": {
            "item_id": item_id,
            "name": f"景点{item_id}",
            "city": "北京",
            "day": day,
            "start_time": start,
            "duration_minutes": duration,
            "poi_id": poi_id,
        },
    }


# --- create / list / get -------------------------------------------------------


def test_create_returns_201_summary():
    client = make_app()
    body = create_itinerary(client)
    assert body["working_sync_version"] == 1
    assert body["cities"] == ["北京"]
    assert body["itinerary_id"]


def test_list_returns_only_callers_own_itineraries():
    client = make_app()
    create_itinerary(client, DEV_A)
    create_itinerary(client, DEV_A, cities=["上海"])
    create_itinerary(client, DEV_B)
    resp = client.get("/api/v1/itineraries", headers=DEV_A)
    assert resp.status_code == 200
    summaries = resp.json()
    assert len(summaries) == 2
    assert {s["cities"][0] for s in summaries} == {"北京", "上海"}


def test_get_returns_full_record_with_snapshot_metadata():
    client = make_app()
    record = create_itinerary(client)
    resp = client.post(
        f"/api/v1/itineraries/{record['itinerary_id']}/snapshots",
        json={},
        headers=DEV_A,
    )
    assert resp.status_code == 201
    resp = client.get(f"/api/v1/itineraries/{record['itinerary_id']}", headers=DEV_A)
    assert resp.status_code == 200
    full = resp.json()
    assert full["working_sync_version"] == 1
    assert len(full["plan"]["days"]) == 2
    assert len(full["snapshots"]) == 1
    assert full["snapshots"][0]["plan"]["cities"] == ["北京"]  # plan included
    assert full["active_snapshot_id"] is None


# --- mutate ---------------------------------------------------------------------


def test_put_applies_diffs_and_bumps_version():
    client = make_app()
    record = create_itinerary(client)
    resp = client.put(
        f"/api/v1/itineraries/{record['itinerary_id']}",
        json={"diffs": [add_diff("a")]},
        headers=DEV_A,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["record"]["working_sync_version"] == 2
    assert body["validation"]["ok"] is True
    assert body["change_summary"]["affected_items_count"] == 1


def test_put_error_violation_returns_422_and_keeps_version():
    client = make_app()
    record = create_itinerary(client)
    resp = client.put(
        f"/api/v1/itineraries/{record['itinerary_id']}",
        json={
            "diffs": [add_diff("bad", start="08:00", duration=60, poi_id="p1")],
            "poi_hours": [{"poi_id": "p1", "opens": "10:00", "closes": "18:00"}],
        },
        headers=DEV_A,
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["ok"] is False
    assert any(v["rule_id"] == 2 for v in detail["violations"])
    # Version frozen: a follow-up GET still sees the untouched record.
    full = client.get(
        f"/api/v1/itineraries/{record['itinerary_id']}", headers=DEV_A
    ).json()
    assert full["working_sync_version"] == 1
    assert full["plan"]["days"][0]["items"] == []


def test_put_invalid_diff_returns_400():
    client = make_app()
    record = create_itinerary(client)
    resp = client.put(
        f"/api/v1/itineraries/{record['itinerary_id']}",
        json={
            "diffs": [{"op": "retime", "item_id": "nope", "new_start_time": "10:00"}]
        },
        headers=DEV_A,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid_diff"


# --- snapshots --------------------------------------------------------------------


def test_snapshot_create_and_list_with_auto_name():
    client = make_app()
    record = create_itinerary(client)
    resp = client.post(
        f"/api/v1/itineraries/{record['itinerary_id']}/snapshots",
        json={"note": "出发前"},
        headers=DEV_A,
    )
    assert resp.status_code == 201
    meta = resp.json()
    assert meta["name"] == "v1"
    assert meta["note"] == "出发前"
    assert meta["sync_version"] == 1
    assert "plan" not in meta

    listed = client.get(
        f"/api/v1/itineraries/{record['itinerary_id']}/snapshots", headers=DEV_A
    )
    assert listed.status_code == 200
    assert [s["name"] for s in listed.json()] == ["v1"]


def test_snapshot_quota_exhausted_returns_402_with_paywall_trigger():
    client = make_app(snapshot_limit=1)
    record = create_itinerary(client)
    url = f"/api/v1/itineraries/{record['itinerary_id']}/snapshots"
    assert client.post(url, json={}, headers=DEV_A).status_code == 201
    resp = client.post(url, json={}, headers=DEV_A)
    assert resp.status_code == 402
    detail = resp.json()["detail"]
    assert detail["paywall_trigger"] == "snapshot_limit_hit"
    assert detail["denied_reason"] == "quota_exhausted"


# --- restore ------------------------------------------------------------------------


def test_restore_returns_updated_record():
    client = make_app()
    record = create_itinerary(client)
    iid = record["itinerary_id"]
    client.put(
        f"/api/v1/itineraries/{iid}", json={"diffs": [add_diff("a")]}, headers=DEV_A
    )
    snap = client.post(
        f"/api/v1/itineraries/{iid}/snapshots", json={}, headers=DEV_A
    ).json()
    client.put(
        f"/api/v1/itineraries/{iid}",
        json={"diffs": [add_diff("b", start="14:00")]},
        headers=DEV_A,
    )
    resp = client.post(
        f"/api/v1/itineraries/{iid}/snapshots/{snap['snapshot_id']}/restore",
        headers=DEV_A,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["working_sync_version"] == 4
    assert body["active_snapshot_id"] == snap["snapshot_id"]
    items = body["plan"]["days"][0]["items"]
    assert [i["item_id"] for i in items] == ["a"]  # back to snapshot state


def test_restore_unknown_snapshot_returns_404():
    client = make_app()
    record = create_itinerary(client)
    resp = client.post(
        f"/api/v1/itineraries/{record['itinerary_id']}/snapshots/snap_x/restore",
        headers=DEV_A,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "snapshot_not_found"


# --- owner isolation + device id ---------------------------------------------


def test_foreign_owner_gets_404_not_403():
    client = make_app()
    record = create_itinerary(client, DEV_A)
    iid = record["itinerary_id"]
    assert client.get(f"/api/v1/itineraries/{iid}", headers=DEV_B).status_code == 404
    assert (
        client.put(
            f"/api/v1/itineraries/{iid}", json={"diffs": []}, headers=DEV_B
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/itineraries/{iid}/snapshots", json={}, headers=DEV_B
        ).status_code
        == 404
    )


def test_missing_device_id_returns_400():
    client = make_app()
    resp = client.post("/api/v1/itineraries", json={"cities": ["北京"], "days": 1})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "missing_device_id"


def test_unknown_itinerary_returns_404():
    client = make_app()
    assert client.get("/api/v1/itineraries/it_none", headers=DEV_A).status_code == 404
