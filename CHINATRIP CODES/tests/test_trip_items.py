"""Trip-center three-state API + state-machine tests (design v2.4 §5/§4)."""

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.trip_items import get_trip_item_service, router
from app.services.trip_items import InvalidTransitionError, TripItemService

CONTRACT_KEYS = {
    "id",
    "itinerary_id",
    "name",
    "city",
    "note",
    "status",
    "source",
    "poi_id",
    "address",
    "opening_hours",
    "day",
    "position",
    "booking_id",
    "created_at",
    "updated_at",
}


def make_app() -> FastAPI:
    """Mini app with a fresh per-test store (navigation-test pattern).
    The override must close over ONE service instance — a fresh call per
    request would hand every request an empty store."""
    app = FastAPI()
    app.include_router(router)
    service = TripItemService()
    app.dependency_overrides[get_trip_item_service] = lambda: service
    return app


def create_item(client: TestClient, **overrides) -> dict:
    body = {"name": "外滩夜景", "source": "manual", **overrides}
    resp = client.post("/api/v1/trip-items", json=body)
    assert resp.status_code == 201
    return resp.json()


def schedule(client: TestClient, item_id: str, day: int, **extra) -> dict:
    resp = client.patch(
        f"/api/v1/trip-items/{item_id}",
        json={"status": "scheduled", "day": day, **extra},
    )
    assert resp.status_code == 200
    return resp.json()


def book(client: TestClient, item_id: str, booking_id: str = "BK-001") -> dict:
    resp = client.patch(
        f"/api/v1/trip-items/{item_id}",
        json={"status": "booked", "booking_id": booking_id},
    )
    assert resp.status_code == 200
    return resp.json()


# --- create ------------------------------------------------------------------


def test_create_returns_201_with_wishlist_defaults():
    with TestClient(make_app()) as client:
        item = create_item(
            client,
            itinerary_id="t1",
            city="上海",
            note="晚上去",
            poi_id="B001",
        )
    assert set(item) == CONTRACT_KEYS
    assert item["status"] == "wishlist"
    assert item["day"] is None
    assert item["position"] is None
    assert item["booking_id"] is None
    assert item["created_at"] == item["updated_at"]
    # iron rule 0: all five origins accepted, same shape
    with TestClient(make_app()) as client:
        for source in ("manual", "chat", "paste", "agent_recommend", "plan_delete"):
            resp = client.post(
                "/api/v1/trip-items", json={"name": f"x-{source}", "source": source}
            )
            assert resp.status_code == 201
            assert resp.json()["source"] == source


def test_create_rejects_unknown_source():
    with TestClient(make_app()) as client:
        resp = client.post(
            "/api/v1/trip-items", json={"name": "x", "source": "web_scraper"}
        )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "invalid_source"


def test_create_requires_name():
    with TestClient(make_app()) as client:
        resp = client.post("/api/v1/trip-items", json={"source": "manual"})
        assert resp.status_code == 422
        resp = client.post("/api/v1/trip-items", json={"name": "", "source": "manual"})
        assert resp.status_code == 422
        resp = client.post(
            "/api/v1/trip-items", json={"name": "x" * 201, "source": "manual"}
        )
        assert resp.status_code == 422


def test_create_carries_address_and_opening_hours():
    """v2.4.3: the trip center keeps the plan's display fields."""
    with TestClient(make_app()) as client:
        item = create_item(
            client,
            address="上海市黄浦区中山东一路",
            opening_hours="全天开放",
        )
    assert item["address"] == "上海市黄浦区中山东一路"
    assert item["opening_hours"] == "全天开放"


# --- dedup (idempotent create) -------------------------------------------------


def test_create_dedups_same_name_city_within_itinerary_across_sources():
    """manual + agent_recommend of the same thing -> one row, existing wins."""
    service = TripItemService()
    first = service.create("西湖", source="manual", itinerary_id="t1", city="杭州")
    second = service.create(
        "  西湖 ", source="agent_recommend", itinerary_id="t1", city="杭州"
    )
    assert second["id"] == first["id"]
    assert second["source"] == "manual"
    assert [i["name"] for i in service.list_groups("t1")["wishlist"]] == ["西湖"]


def test_create_dedups_by_poi_id_even_when_name_differs():
    service = TripItemService()
    first = service.create(
        "西湖", source="manual", itinerary_id="t1", city="杭州", poi_id="B001"
    )
    second = service.create(
        "West Lake", source="chat", itinerary_id="t1", city="杭州", poi_id="B001"
    )
    assert second["id"] == first["id"]


def test_create_dedup_merges_cross_trip_wishlist_but_respects_states():
    """2026-10-28 用户报告：全局心愿板每个行程各出一张 西湖 卡。跨行程的
    wishlist 同名行=同一个愿，合并成一张；他行程已排期 → 新行程自建一行；
    已知不同城市 = 不同地点，永不合并。"""
    service = TripItemService()
    hz = service.create("西湖", source="manual", itinerary_id="t1", city="杭州")
    again = service.create("西湖", source="paste", itinerary_id="t2", city="杭州")
    assert again["id"] == hz["id"]
    service.update(hz["id"], status="scheduled", day=1)
    fresh = service.create("西湖", source="manual", itinerary_id="t3", city="杭州")
    assert fresh["id"] != hz["id"]
    su = service.create("西湖", source="manual", itinerary_id="t3", city="苏州")
    assert su["id"] != fresh["id"]


def test_create_dedup_plan_delete_never_merges_across_trips():
    """trip B 删除 西湖 只在 trip B 落 unwanted，不翻 trip A 的愿。"""
    service = TripItemService()
    wish = service.create("西湖", source="manual", itinerary_id="t1", city="杭州")
    parked = service.mark_unwanted("西湖", itinerary_id="t2", city="杭州")
    assert parked["id"] != wish["id"]
    assert wish["status"] == "wishlist"
    assert parked["status"] == "unwanted"


def test_create_dedup_cityless_matches_named_city_both_orders():
    """chat 只带名字、paste 带城市：同一心愿，谁先谁后都合并。"""
    first = TripItemService()
    bare = first.create("西湖", source="chat")
    named = first.create("西湖", source="paste", city="杭州")
    assert named["id"] == bare["id"]

    second = TripItemService()
    named2 = second.create("西湖", source="paste", city="杭州")
    bare2 = second.create("西湖", source="chat")
    assert bare2["id"] == named2["id"]


def test_create_dedup_ignores_unwanted_rows():
    """A rejected item does not block re-adding: fresh wishlist row."""
    service = TripItemService()
    parked = service.mark_unwanted("西湖", itinerary_id="t1", city="杭州")
    fresh = service.create("西湖", source="manual", itinerary_id="t1", city="杭州")
    assert fresh["id"] != parked["id"]
    assert fresh["status"] == "wishlist"
    groups = service.list_groups("t1")
    assert [i["name"] for i in groups["unwanted"]] == ["西湖"]
    assert [i["name"] for i in groups["wishlist"]] == ["西湖"]


def test_create_dedup_over_api_returns_201_with_existing_id():
    with TestClient(make_app()) as client:
        first = create_item(client, itinerary_id="t1", city="上海")
        resp = client.post(
            "/api/v1/trip-items",
            json={
                "name": "外滩夜景",
                "source": "chat",
                "itinerary_id": "t1",
                "city": "上海",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["id"] == first["id"]
        board = client.get("/api/v1/trip-items", params={"itinerary_id": "t1"}).json()
        assert len(board["wishlist"]) == 1


def test_mark_unwanted_fallback_absorbs_normalized_active_match():
    """Loop misses (exact name), create-level dedup catches (normalized):
    the active row is parked instead of a shadow unwanted twin."""
    service = TripItemService()
    item = service.create("West Lake", source="manual", itinerary_id="t1")
    parked = service.mark_unwanted("west lake", itinerary_id="t1")
    assert parked["id"] == item["id"]
    assert parked["status"] == "unwanted"


# --- list ----------------------------------------------------------------------


def test_list_groups_and_orders_three_states():
    with TestClient(make_app()) as client:
        create_item(client, itinerary_id="t1", name="w1")
        time.sleep(0.005)
        create_item(client, itinerary_id="t1", name="w2")
        s_day2 = create_item(client, itinerary_id="t1", name="s-day2")
        s_day1_first = create_item(client, itinerary_id="t1", name="s-day1-a")
        s_day1_second = create_item(client, itinerary_id="t1", name="s-day1-b")
        b_day2 = create_item(client, itinerary_id="t1", name="b-day2")
        b_day1 = create_item(client, itinerary_id="t1", name="b-day1")
        other = create_item(client, itinerary_id="t2", name="other-trip")

        schedule(client, s_day2["id"], day=2)  # pos 1.0
        schedule(client, s_day1_first["id"], day=1)  # pos 1.0
        schedule(client, s_day1_second["id"], day=1)  # pos 2.0
        schedule(client, b_day2["id"], day=2)  # pos 2.0
        schedule(client, b_day1["id"], day=1)  # pos 3.0
        book(client, b_day2["id"], "BK-D2")
        book(client, b_day1["id"], "BK-D1")

        resp = client.get("/api/v1/trip-items", params={"itinerary_id": "t1"})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"bookings", "wishlist", "scheduled", "unwanted"}
    assert [i["name"] for i in body["bookings"]] == ["b-day1", "b-day2"]
    assert [i["name"] for i in body["scheduled"]] == [
        "s-day1-a",
        "s-day1-b",
        "s-day2",
    ]
    # wishlist stream: newest first
    assert [i["name"] for i in body["wishlist"]] == ["w2", "w1"]
    assert all(i["name"] != other["name"] for group in body.values() for i in group)

    # without the filter the other trip's item is visible too
    with TestClient(make_app()) as client:
        create_item(client, itinerary_id="t2", name="other-trip")
        resp = client.get("/api/v1/trip-items")
    assert resp.status_code == 200
    assert len(resp.json()["wishlist"]) == 1


# --- transitions: wishlist -> scheduled ---------------------------------------


def test_schedule_appends_position_within_day_and_honors_explicit():
    with TestClient(make_app()) as client:
        a = create_item(client, itinerary_id="t1", name="a")
        b = create_item(client, itinerary_id="t1", name="b")
        c = create_item(client, itinerary_id="t1", name="c")
        first = schedule(client, a["id"], day=1)
        second = schedule(client, b["id"], day=1)
        explicit = schedule(client, c["id"], day=1, position=9.5)
    assert first["status"] == "scheduled"
    assert first["day"] == 1
    assert first["position"] == 1.0
    assert first["booking_id"] is None
    assert second["position"] == 2.0
    assert explicit["position"] == 9.5


def test_schedule_missing_day_returns_422():
    with TestClient(make_app()) as client:
        item = create_item(client)
        resp = client.patch(
            f"/api/v1/trip-items/{item['id']}", json={"status": "scheduled"}
        )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "invalid_transition"


def test_schedule_day_below_one_returns_422():
    with TestClient(make_app()) as client:
        item = create_item(client)
        resp = client.patch(
            f"/api/v1/trip-items/{item['id']}",
            json={"status": "scheduled", "day": 0},
        )
    assert resp.status_code == 422


# --- transitions: scheduled -> booked ------------------------------------------


def test_book_requires_non_empty_booking_id_and_keeps_slot():
    with TestClient(make_app()) as client:
        item = create_item(client, itinerary_id="t1")
        schedule(client, item["id"], day=2)

        missing = client.patch(
            f"/api/v1/trip-items/{item['id']}", json={"status": "booked"}
        )
        empty = client.patch(
            f"/api/v1/trip-items/{item['id']}",
            json={"status": "booked", "booking_id": "  "},
        )
        assert missing.status_code == 422
        assert missing.json()["detail"] == "invalid_transition"
        assert empty.status_code == 422

        booked = book(client, item["id"], "BK-777")
    assert booked["status"] == "booked"
    assert booked["booking_id"] == "BK-777"
    assert booked["day"] == 2
    assert booked["position"] == 1.0


# --- transitions: un-schedule ---------------------------------------------------


def test_unschedule_from_scheduled_clears_day_and_position():
    with TestClient(make_app()) as client:
        item = create_item(client, itinerary_id="t1")
        schedule(client, item["id"], day=3)
        resp = client.patch(
            f"/api/v1/trip-items/{item['id']}", json={"status": "wishlist"}
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "wishlist"
    assert body["day"] is None
    assert body["position"] is None
    assert body["booking_id"] is None


def test_unschedule_from_booked_also_clears_booking_id():
    with TestClient(make_app()) as client:
        item = create_item(client, itinerary_id="t1")
        schedule(client, item["id"], day=1)
        book(client, item["id"], "BK-9")
        resp = client.patch(
            f"/api/v1/trip-items/{item['id']}", json={"status": "wishlist"}
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "wishlist"
    assert body["day"] is None
    assert body["position"] is None
    assert body["booking_id"] is None


# --- transitions: mark unwanted --------------------------------------------------


def test_unwanted_from_any_state_clears_fields():
    with TestClient(make_app()) as client:
        sched = create_item(client, itinerary_id="t1", name="s")
        schedule(client, sched["id"], day=2)
        r_sched = client.patch(
            f"/api/v1/trip-items/{sched['id']}", json={"status": "unwanted"}
        )
        booked = create_item(client, itinerary_id="t1", name="b")
        schedule(client, booked["id"], day=1)
        book(client, booked["id"], "BK-U")
        r_booked = client.patch(
            f"/api/v1/trip-items/{booked['id']}", json={"status": "unwanted"}
        )
        wish = create_item(client, itinerary_id="t1", name="w")
        r_wish = client.patch(
            f"/api/v1/trip-items/{wish['id']}", json={"status": "unwanted"}
        )
    for resp in (r_sched, r_booked, r_wish):
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "unwanted"
        assert body["day"] is None
        assert body["position"] is None
        assert body["booking_id"] is None


def test_unwanted_restore_to_wishlist_then_reschedule():
    with TestClient(make_app()) as client:
        item = create_item(client, itinerary_id="t1")
        schedule(client, item["id"], day=1)
        client.patch(f"/api/v1/trip-items/{item['id']}", json={"status": "unwanted"})
        resp = client.patch(
            f"/api/v1/trip-items/{item['id']}", json={"status": "wishlist"}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "wishlist"
        rescheduled = schedule(client, item["id"], day=3)
    assert rescheduled["position"] == 1.0


def test_unwanted_walkback_to_timeline_stays_422():
    with TestClient(make_app()) as client:
        item = create_item(client)
        client.patch(f"/api/v1/trip-items/{item['id']}", json={"status": "unwanted"})
        to_sched = client.patch(
            f"/api/v1/trip-items/{item['id']}", json={"status": "scheduled", "day": 1}
        )
        to_booked = client.patch(
            f"/api/v1/trip-items/{item['id']}",
            json={"status": "booked", "booking_id": "BK-1"},
        )
    assert to_sched.status_code == 422
    assert to_booked.status_code == 422


def test_list_groups_unwanted_sorted_newest_first():
    with TestClient(make_app()) as client:
        a = create_item(client, itinerary_id="t1", name="u-a")
        b = create_item(client, itinerary_id="t1", name="u-b")
        time.sleep(0.005)
        client.patch(f"/api/v1/trip-items/{a['id']}", json={"status": "unwanted"})
        time.sleep(0.005)
        client.patch(f"/api/v1/trip-items/{b['id']}", json={"status": "unwanted"})
        resp = client.get("/api/v1/trip-items", params={"itinerary_id": "t1"})
    assert resp.status_code == 200
    assert [i["name"] for i in resp.json()["unwanted"]] == ["u-b", "u-a"]


# --- illegal transitions ---------------------------------------------------------


def test_illegal_transitions_return_422():
    with TestClient(make_app()) as client:
        # wishlist -> booked directly (skipping the schedule step)
        wish = create_item(client)
        resp = client.patch(
            f"/api/v1/trip-items/{wish['id']}",
            json={"status": "booked", "booking_id": "BK-1"},
        )
        assert resp.status_code == 422
        assert resp.json()["detail"] == "invalid_transition"

        # booked -> scheduled (status walk-back other than un-schedule)
        item = create_item(client, itinerary_id="t1")
        schedule(client, item["id"], day=1)
        book(client, item["id"], "BK-2")
        resp = client.patch(
            f"/api/v1/trip-items/{item['id']}", json={"status": "scheduled"}
        )
        assert resp.status_code == 422

        # unknown status value
        resp = client.patch(
            f"/api/v1/trip-items/{item['id']}", json={"status": "flying"}
        )
        assert resp.status_code == 422
        assert resp.json()["detail"] == "invalid_transition"


# --- plain field patches -----------------------------------------------------------


def test_patch_updates_note_city_and_bumps_updated_at():
    with TestClient(make_app()) as client:
        item = create_item(client, city="杭州", note="orig")
        time.sleep(0.005)
        resp = client.patch(
            f"/api/v1/trip-items/{item['id']}",
            json={"note": "改到周六", "city": "苏州"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["note"] == "改到周六"
    assert body["city"] == "苏州"
    assert body["status"] == "wishlist"  # plain patch must not move the state
    assert body["created_at"] == item["created_at"]
    assert body["updated_at"] > item["created_at"]


# --- delete -------------------------------------------------------------------------


def test_delete_wishlist_and_scheduled_returns_204():
    with TestClient(make_app()) as client:
        wish = create_item(client)
        sched = create_item(client, itinerary_id="t1", name="灵隐寺")
        # 2026-10-28 起跨行程同名 wishlist 合并 → DELETE 用例改用不同名
        schedule(client, sched["id"], day=1)
        for item_id in (wish["id"], sched["id"]):
            resp = client.delete(f"/api/v1/trip-items/{item_id}")
            assert resp.status_code == 204
            assert client.get(f"/api/v1/trip-items/{item_id}").status_code == 404


def test_delete_booked_returns_422_until_unbooked():
    with TestClient(make_app()) as client:
        item = create_item(client, itinerary_id="t1")
        schedule(client, item["id"], day=1)
        book(client, item["id"], "BK-3")
        resp = client.delete(f"/api/v1/trip-items/{item['id']}")
        assert resp.status_code == 422
        assert resp.json()["detail"] == "invalid_transition"

        client.patch(f"/api/v1/trip-items/{item['id']}", json={"status": "wishlist"})
        assert client.delete(f"/api/v1/trip-items/{item['id']}").status_code == 204


# --- 404s ---------------------------------------------------------------------------


def test_get_patch_delete_unknown_id_return_404():
    with TestClient(make_app()) as client:
        assert client.get("/api/v1/trip-items/nope").status_code == 404
        assert client.get("/api/v1/trip-items/nope").json()["detail"] == "not_found"
        resp = client.patch("/api/v1/trip-items/nope", json={"note": "x"})
        assert resp.status_code == 404
        assert client.delete("/api/v1/trip-items/nope").status_code == 404


# --- service layer (pure logic) + wiring ----------------------------------------------


def test_service_singleton_dependency_returns_same_instance():
    assert get_trip_item_service() is get_trip_item_service()


def test_service_position_default_scopes_to_itinerary_and_day():
    service = TripItemService()
    trip_a = service.create("a", source="manual", itinerary_id="t1")
    trip_b = service.create("b", source="chat", itinerary_id="t2")
    other_day = service.create("c", source="paste", itinerary_id="t1")
    service.update(trip_a["id"], status="scheduled", day=1)
    service.update(other_day["id"], status="scheduled", day=2)
    # different trip, same day -> independent bucket
    assert service.update(trip_b["id"], status="scheduled", day=1)["position"] == 1.0
    # same trip, same day -> appended after the first
    second = service.create("d", source="agent_recommend", itinerary_id="t1")
    assert service.update(second["id"], status="scheduled", day=1)["position"] == 2.0


def test_service_transition_rules_direct():
    service = TripItemService()
    item = service.create("x", source="manual")
    with pytest.raises(InvalidTransitionError):
        service.update(item["id"], status="booked", booking_id="BK")  # skip state
    service.update(item["id"], status="scheduled", day=1)
    with pytest.raises(InvalidTransitionError):
        service.update(item["id"], status="booked", booking_id="")  # empty id
    booked = service.update(item["id"], status="booked", booking_id="BK")
    with pytest.raises(InvalidTransitionError):
        service.update(item["id"], status="scheduled")  # walk-back wrong way
    with pytest.raises(InvalidTransitionError):
        service.delete(booked["id"])  # booked is not deletable
    cleared = service.update(item["id"], status="wishlist")
    assert cleared["booking_id"] is None and cleared["day"] is None
    service.delete(item["id"])  # wishlist deletes cleanly
    assert service.get(item["id"]) is None


def test_mark_unwanted_parks_matching_item_and_clears_fields():
    service = TripItemService()
    item = service.create(
        "西湖", source="agent_recommend", itinerary_id="t1", city="杭州"
    )
    service.update(item["id"], status="scheduled", day=2)
    parked = service.mark_unwanted("西湖", itinerary_id="t1")
    assert parked["id"] == item["id"]
    assert parked["status"] == "unwanted"
    assert parked["day"] is None
    assert parked["position"] is None
    assert parked["booking_id"] is None


def test_mark_unwanted_already_unwanted_returns_as_is():
    service = TripItemService()
    first = service.mark_unwanted("外滩", itinerary_id="t1")
    again = service.mark_unwanted("外滩", itinerary_id="t1")
    assert again["id"] == first["id"]
    assert again["updated_at"] == first["updated_at"]


def test_mark_unwanted_not_found_creates_plan_delete_entry():
    service = TripItemService()
    parked = service.mark_unwanted("新天地", itinerary_id="t1", city="上海")
    assert parked["source"] == "plan_delete"
    assert parked["status"] == "unwanted"
    assert parked["name"] == "新天地"
    assert parked["city"] == "上海"
    assert [i["name"] for i in service.list_groups("t1")["unwanted"]] == ["新天地"]


def test_mark_unwanted_scopes_to_itinerary_and_exact_name():
    service = TripItemService()
    other_trip = service.create("外滩", source="manual", itinerary_id="t2")
    parked = service.mark_unwanted("外滩", itinerary_id="t1")
    assert parked["itinerary_id"] == "t1"
    assert service.get(other_trip["id"])["status"] == "wishlist"


def test_router_wires_all_five_paths():
    paths = {route.path for route in router.routes}
    assert {
        "/api/v1/trip-items",
        "/api/v1/trip-items/{item_id}",
    } <= paths
    collection = [
        route.methods for route in router.routes if route.path == "/api/v1/trip-items"
    ]
    assert {"POST", "GET"} <= set().union(*collection)


# --- persistence (2026-10-23 心愿单蒸发 fix) ------------------------------------


def test_persistent_service_survives_reinstall(tmp_path):
    """A fresh service over the same DB sees prior writes: create/schedule
    round-trip, delete is honored, corrupt rows are skipped not fatal."""
    from app.services.state_persist import (
        PersistentTripItemService,
        SqliteStateBackend,
    )

    db = str(tmp_path / "state.db")
    svc = PersistentTripItemService(SqliteStateBackend(db))
    item = svc.create("外滩", source="manual", itinerary_id="t1", city="上海")
    svc.update(item["id"], status="scheduled", day=2)
    keeper = svc.create("留着的", source="chat", itinerary_id="t1")

    reloaded = PersistentTripItemService(SqliteStateBackend(db))
    loaded = reloaded.get(item["id"])
    assert loaded["name"] == "外滩"
    assert loaded["status"] == "scheduled"
    assert loaded["day"] == 2
    assert reloaded.get(keeper["id"])["status"] == "wishlist"

    reloaded.delete(keeper["id"])
    again = PersistentTripItemService(SqliteStateBackend(db))
    assert again.get(keeper["id"]) is None
    assert again.get(item["id"])["status"] == "scheduled"


def test_persistent_service_skips_corrupt_row(tmp_path):
    from app.services.state_persist import (
        PersistentTripItemService,
        SqliteStateBackend,
    )

    db = str(tmp_path / "state.db")
    backend = SqliteStateBackend(db)
    backend.save_trip_item("bad", "{not json")
    service = PersistentTripItemService(backend)
    assert service.get("bad") is None
    assert "bad" in backend.load_trip_items()  # row left on disk, not fatal


def test_persistent_mark_unwanted_write_through(tmp_path):
    """mark_unwanted rides create/update internally — both land on disk."""
    from app.services.state_persist import (
        PersistentTripItemService,
        SqliteStateBackend,
    )

    db = str(tmp_path / "state.db")
    svc = PersistentTripItemService(SqliteStateBackend(db))
    svc.mark_unwanted("新天地", itinerary_id="t1", city="上海")
    reloaded = PersistentTripItemService(SqliteStateBackend(db))
    assert [i["name"] for i in reloaded.list_groups("t1")["unwanted"]] == ["新天地"]
