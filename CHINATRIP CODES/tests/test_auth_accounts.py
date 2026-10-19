# -*- coding: utf-8 -*-
"""Custom username+password accounts: multi-device itinerary login.

App assembly mirrors tests/test_itineraries_api.py: fresh store +
entitlement + AccountService (tmp SQLite db) per app via
dependency_overrides, so accounts and quota counters never leak across
tests.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth import router as auth_router
from app.api.itineraries import (
    get_account_service,
    get_entitlement_service,
    get_store,
)
from app.api.itineraries import router as itineraries_router
from app.services.accounts import AccountService
from app.services.entitlement import EntitlementService, InMemoryQuotaStore
from app.services.itinerary_store import InMemoryItineraryStore
from app.services.state_persist import SqliteStateBackend

DEV_A = {"X-Device-ID": "device-a"}
DEV_B = {"X-Device-ID": "device-b"}


def make_client(tmp_path) -> TestClient:
    store = InMemoryItineraryStore()
    account = AccountService(SqliteStateBackend(str(tmp_path / "accounts.db")), store)
    entitlement = EntitlementService(
        InMemoryQuotaStore(), rules=[], quotas={"snapshot_limit": 3}
    )
    app = FastAPI()
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_account_service] = lambda: account
    app.dependency_overrides[get_entitlement_service] = lambda: entitlement
    app.include_router(itineraries_router)
    app.include_router(auth_router)
    return TestClient(app)


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def auth_headers(token: str, device=DEV_B) -> dict:
    return {**device, **bearer(token)}


def register(
    client: TestClient, username="alice", password="secret6", headers=DEV_A
) -> dict:
    resp = client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": password},
        headers=headers,
    )
    assert resp.status_code == 201
    return resp.json()


def login(
    client: TestClient, username="alice", password="secret6", headers=DEV_B
) -> dict:
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
        headers=headers,
    )
    assert resp.status_code == 200
    return resp.json()


def create_itinerary(client: TestClient, headers=DEV_A) -> dict:
    resp = client.post(
        "/api/v1/itineraries", json={"cities": ["北京"], "days": 2}, headers=headers
    )
    assert resp.status_code == 201
    return resp.json()


def add_diff(item_id: str) -> dict:
    return {
        "op": "add",
        "item": {
            "item_id": item_id,
            "name": f"景点{item_id}",
            "city": "北京",
            "day": 1,
            "start_time": "10:00",
            "duration_minutes": 120,
            "poi_id": None,
        },
    }


# --- register -----------------------------------------------------------------


def test_register_returns_token_and_zero_claims(tmp_path):
    client = make_client(tmp_path)
    body = register(client)
    assert body["token"]
    assert body["username"] == "alice"
    assert body["claimed"] == 0


def test_register_duplicate_username_400(tmp_path):
    client = make_client(tmp_path)
    register(client)
    resp = client.post(
        "/api/v1/auth/register",
        json={"username": "alice", "password": "secret6"},
        headers=DEV_B,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "username_taken"


def test_register_short_password_400(tmp_path):
    client = make_client(tmp_path)
    resp = client.post(
        "/api/v1/auth/register",
        json={"username": "alice", "password": "12345"},
        headers=DEV_A,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid_username_or_password"


def test_register_username_with_inner_space_400(tmp_path):
    client = make_client(tmp_path)
    resp = client.post(
        "/api/v1/auth/register",
        json={"username": "ali ce", "password": "secret6"},
        headers=DEV_A,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid_username_or_password"


def test_register_short_username_400(tmp_path):
    client = make_client(tmp_path)
    resp = client.post(
        "/api/v1/auth/register",
        json={"username": "a", "password": "secret6"},
        headers=DEV_A,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid_username_or_password"


# --- login / token lifecycle ----------------------------------------------------


def test_login_wrong_password_401(tmp_path):
    client = make_client(tmp_path)
    register(client)
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "wrongpw"},
        headers=DEV_B,
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "invalid_credentials"


def test_login_unknown_user_401(tmp_path):
    client = make_client(tmp_path)
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "nobody", "password": "secret6"},
        headers=DEV_B,
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "invalid_credentials"


def test_login_ok_200(tmp_path):
    client = make_client(tmp_path)
    register(client)
    body = login(client)
    assert body["token"]
    assert body["username"] == "alice"


def test_me_echoes_username(tmp_path):
    client = make_client(tmp_path)
    token = register(client)["token"]
    resp = client.get("/api/v1/auth/me", headers=bearer(token))
    assert resp.status_code == 200
    assert resp.json() == {"username": "alice"}


def test_me_bad_token_401(tmp_path):
    client = make_client(tmp_path)
    resp = client.get("/api/v1/auth/me", headers=bearer("garbage"))
    assert resp.status_code == 401


def test_me_missing_header_401(tmp_path):
    client = make_client(tmp_path)
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401


def test_logout_invalidates_token(tmp_path):
    client = make_client(tmp_path)
    token = register(client)["token"]
    resp = client.post("/api/v1/auth/logout", headers=bearer(token))
    assert resp.status_code == 204
    assert client.get("/api/v1/auth/me", headers=bearer(token)).status_code == 401


def test_logout_bad_token_401(tmp_path):
    client = make_client(tmp_path)
    resp = client.post("/api/v1/auth/logout", headers=bearer("garbage"))
    assert resp.status_code == 401


def test_relogin_rotates_token(tmp_path):
    client = make_client(tmp_path)
    token1 = register(client)["token"]
    token2 = login(client)["token"]
    assert token1 != token2
    assert client.get("/api/v1/auth/me", headers=bearer(token1)).status_code == 401
    assert client.get("/api/v1/auth/me", headers=bearer(token2)).status_code == 200


# --- claim flow ---------------------------------------------------------------


def test_register_claims_current_device_itineraries(tmp_path):
    client = make_client(tmp_path)
    create_itinerary(client, DEV_A)
    create_itinerary(client, DEV_A)
    create_itinerary(client, DEV_B)  # other device: not claimed
    body = register(client, headers=DEV_A)
    assert body["claimed"] == 2
    # Logged-in listing is account-wide: 2, from any device.
    listed = client.get("/api/v1/itineraries", headers=auth_headers(body["token"]))
    assert len(listed.json()) == 2
    # Same token on device B sees the same two.
    listed_b = client.get(
        "/api/v1/itineraries", headers={**DEV_B, **bearer(body["token"])}
    )
    assert len(listed_b.json()) == 2
    # Device B without a token still sees only its own (anonymous) one.
    assert len(client.get("/api/v1/itineraries", headers=DEV_B).json()) == 1


def test_login_claims_new_device_itineraries(tmp_path):
    client = make_client(tmp_path)
    register(client, headers=DEV_A)
    create_itinerary(client, DEV_B)  # anonymous on the second device
    body = login(client, headers=DEV_B)
    assert body["claimed"] == 1


def test_claim_is_idempotent_for_already_claimed(tmp_path):
    client = make_client(tmp_path)
    create_itinerary(client, DEV_A)
    register(client, headers=DEV_A)
    body = login(client, headers=DEV_A)
    assert body["claimed"] == 0


# --- cross-device access -------------------------------------------------------


def test_cross_device_get_and_mutate(tmp_path):
    client = make_client(tmp_path)
    record = create_itinerary(client, DEV_A)
    token = register(client, headers=DEV_A)["token"]
    iid = record["itinerary_id"]
    headers = auth_headers(token, DEV_B)
    assert client.get(f"/api/v1/itineraries/{iid}", headers=headers).status_code == 200
    resp = client.put(
        f"/api/v1/itineraries/{iid}", json={"diffs": [add_diff("a")]}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["record"]["working_sync_version"] == 2


def test_cross_device_snapshot_and_restore(tmp_path):
    client = make_client(tmp_path)
    record = create_itinerary(client, DEV_A)
    token = register(client, headers=DEV_A)["token"]
    iid = record["itinerary_id"]
    headers = auth_headers(token, DEV_B)
    snap = client.post(f"/api/v1/itineraries/{iid}/snapshots", json={}, headers=headers)
    assert snap.status_code == 201
    resp = client.post(
        f"/api/v1/itineraries/{iid}/snapshots/{snap.json()['snapshot_id']}/restore",
        headers=headers,
    )
    assert resp.status_code == 200


def test_create_while_logged_in_belongs_to_account(tmp_path):
    client = make_client(tmp_path)
    token = register(client, headers=DEV_A)["token"]
    record = create_itinerary(client, {**DEV_A, **bearer(token)})
    ids = [
        s["itinerary_id"]
        for s in client.get("/api/v1/itineraries", headers=auth_headers(token)).json()
    ]
    assert record["itinerary_id"] in ids


def test_other_account_cannot_see_or_touch(tmp_path):
    client = make_client(tmp_path)
    record = create_itinerary(client, DEV_A)
    register(client, headers=DEV_A)  # alice claims it
    register(client, username="bob", password="secret6", headers=DEV_B)
    token_b = login(client, username="bob", headers=DEV_B)["token"]
    foreign = client.get("/api/v1/itineraries", headers=auth_headers(token_b))
    assert foreign.json() == []
    iid = record["itinerary_id"]
    resp = client.get(f"/api/v1/itineraries/{iid}", headers=auth_headers(token_b))
    assert resp.status_code == 404


# --- anonymous path: zero regression ---------------------------------------------


def test_anonymous_list_scoped_to_device(tmp_path):
    client = make_client(tmp_path)
    create_itinerary(client, DEV_A)
    assert len(client.get("/api/v1/itineraries", headers=DEV_A).json()) == 1
    assert client.get("/api/v1/itineraries", headers=DEV_B).json() == []


def test_anonymous_foreign_owner_still_404(tmp_path):
    client = make_client(tmp_path)
    record = create_itinerary(client, DEV_A)
    assert (
        client.get(
            f"/api/v1/itineraries/{record['itinerary_id']}", headers=DEV_B
        ).status_code
        == 404
    )


def test_bad_bearer_token_falls_back_to_anonymous(tmp_path):
    client = make_client(tmp_path)
    create_itinerary(client, DEV_A)
    resp = client.get("/api/v1/itineraries", headers={**DEV_A, **bearer("garbage")})
    assert resp.status_code == 200
    assert len(resp.json()) == 1
