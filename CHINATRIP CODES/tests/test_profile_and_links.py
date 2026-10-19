"""Profile (agent memory) + link-history API tests (design v2.4 §6.14)."""

from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.profile import (
    get_link_store,
    get_profile_store,
    links_router,
    profile_router,
)
from app.services.profile_store import (
    LinkStore,
    ProfileStore,
    default_profile,
    distill_facts,
    new_profile_state,
)

FIXED_NOW = datetime(2026, 10, 18, 12, 0, 0)
DEV = {"X-Device-ID": "dev-1"}
DEV2 = {"X-Device-ID": "dev-2"}


def make_id_factory(prefix: str):
    counter = iter(range(1000))
    return lambda: f"{prefix}{next(counter):04d}"


def make_client() -> TestClient:
    app = FastAPI()
    app.include_router(profile_router)
    app.include_router(links_router)
    profile_store = ProfileStore(
        clock=lambda: FIXED_NOW, id_factory=make_id_factory("applied")
    )
    app.dependency_overrides[get_profile_store] = lambda: profile_store
    # links keep the real clock so created_at ordering is exercised
    link_store = LinkStore()  # one instance per app, not per request
    app.dependency_overrides[get_link_store] = lambda: link_store
    return TestClient(app)


def distill(client: TestClient, facts: list[dict], headers=DEV) -> dict:
    return client.post(
        "/api/v1/profile/distill", json={"facts": facts}, headers=headers
    )


# --- profile: view + merge ------------------------------------------------------


def test_get_profile_returns_default_empty():
    with make_client() as client:
        resp = client.get("/api/v1/profile", headers=DEV)
    assert resp.status_code == 200
    body = resp.json()
    assert body["profile"] == default_profile()
    assert body["updated_at"]


def test_put_partial_merges_and_keeps_absent_fields():
    with make_client() as client:
        resp = client.put(
            "/api/v1/profile", json={"budget_level": "comfort"}, headers=DEV
        )
        assert resp.status_code == 200
        profile = resp.json()["profile"]
        assert profile["budget_level"] == "comfort"
        assert profile["stamina"] is None
        assert profile["travel_style"] == []
        resp = client.put("/api/v1/profile", json={"stamina": "high"}, headers=DEV)
        profile = resp.json()["profile"]
        assert profile["stamina"] == "high"
        assert profile["budget_level"] == "comfort"  # absent field untouched


def test_put_invalid_enum_returns_422():
    with make_client() as client:
        resp = client.put(
            "/api/v1/profile", json={"budget_level": "ultra"}, headers=DEV
        )
        assert resp.status_code == 422
        assert resp.json()["detail"] == "invalid_profile"
        resp = client.put("/api/v1/profile", json={"companions": "pets"}, headers=DEV)
        assert resp.status_code == 422


def test_put_invalid_list_items_return_422():
    with make_client() as client:
        resp = client.put(
            "/api/v1/profile", json={"travel_style": ["摄影", ""]}, headers=DEV
        )
        assert resp.status_code == 422
        resp = client.put(
            "/api/v1/profile",
            json={"travel_style": [f"s{i}" for i in range(21)]},
            headers=DEV,
        )
        assert resp.status_code == 422
        assert resp.json()["detail"] == "invalid_profile"


def test_put_explicit_null_clears_and_blocks_distill():
    with make_client() as client:
        client.put("/api/v1/profile", json={"budget_level": "comfort"}, headers=DEV)
        resp = client.put("/api/v1/profile", json={"budget_level": None}, headers=DEV)
        assert resp.json()["profile"]["budget_level"] is None
        body = distill(
            client,
            [
                {
                    "key": "budget_level",
                    "value": "economy",
                    "confidence": 0.95,
                    "provenance": "chat",
                }
            ],
        ).json()
        assert body["applied"] == []
        assert body["suggestions"][0]["key"] == "budget_level"


# --- profile: distill -------------------------------------------------------------


def test_distill_applies_high_confidence_and_suggests_low():
    facts = [
        {"key": "stamina", "value": "high", "confidence": 0.9, "provenance": "chat"},
        {
            "key": "budget_level",
            "value": "economy",
            "confidence": 0.5,
            "provenance": "chat",
        },
    ]
    with make_client() as client:
        body = distill(client, facts).json()
        assert [a["key"] for a in body["applied"]] == ["stamina"]
        assert body["applied"][0]["applied_id"]
        assert body["suggestions"] == [
            {"key": "budget_level", "value": "economy", "confidence": 0.5}
        ]
        profile = client.get("/api/v1/profile", headers=DEV).json()["profile"]
        assert profile["stamina"] == "high"
        assert profile["budget_level"] is None  # low confidence not written


def test_distill_respects_manually_set():
    with make_client() as client:
        client.put("/api/v1/profile", json={"budget_level": "luxury"}, headers=DEV)
        body = distill(
            client,
            [
                {
                    "key": "budget_level",
                    "value": "economy",
                    "confidence": 0.95,
                    "provenance": "chat",
                }
            ],
        ).json()
        assert body["applied"] == []
        assert body["suggestions"][0]["key"] == "budget_level"
        profile = client.get("/api/v1/profile", headers=DEV).json()["profile"]
        assert profile["budget_level"] == "luxury"


def test_distill_list_merge_dedupes():
    fact = {
        "key": "travel_style",
        "value": ["摄影", "徒步"],
        "confidence": 0.9,
        "provenance": "chat",
    }
    with make_client() as client:
        distill(client, [fact])
        distill(client, [fact])
        profile = client.get("/api/v1/profile", headers=DEV).json()["profile"]
        assert profile["travel_style"] == ["摄影", "徒步"]


def test_distill_notes_appends_with_provenance():
    with make_client() as client:
        body = distill(
            client,
            [
                {
                    "key": "notes",
                    "value": "怕辣",
                    "confidence": 0.85,
                    "provenance": "chat",
                }
            ],
        ).json()
        assert body["applied"][0]["key"] == "notes"
        profile = client.get("/api/v1/profile", headers=DEV).json()["profile"]
        note = profile["notes"][0]
        assert note["text"] == "怕辣"
        assert note["provenance"] == "chat"
        assert note["added_at"] == FIXED_NOW.isoformat()


def test_distill_invalid_key_or_value_returns_422():
    with make_client() as client:
        resp = distill(
            client,
            [
                {
                    "key": "mood",
                    "value": "happy",
                    "confidence": 0.9,
                    "provenance": "chat",
                }
            ],
        )
        assert resp.status_code == 422
        assert resp.json()["detail"] == "invalid_fact"
        resp = distill(
            client,
            [
                {
                    "key": "budget_level",
                    "value": "wrong",
                    "confidence": 0.9,
                    "provenance": "chat",
                }
            ],
        )
        assert resp.status_code == 422


def test_distill_facts_pure_function_is_deterministic():
    state = new_profile_state(FIXED_NOW)
    state.manually_set.add("budget_level")
    facts = [
        {
            "key": "budget_level",
            "value": "luxury",
            "confidence": 0.99,
            "provenance": "chat",
        },
        {"key": "stamina", "value": "high", "confidence": 0.9, "provenance": "chat"},
    ]
    run1 = distill_facts(
        state, facts, now=FIXED_NOW, id_factory=make_id_factory("applied")
    )
    run2 = distill_facts(
        state, facts, now=FIXED_NOW, id_factory=make_id_factory("applied")
    )
    assert run1[1] == run2[1] and run1[2] == run2[2]  # applied + suggestions
    assert run1[0].profile == run2[0].profile
    assert state.profile == default_profile()  # caller state never mutated
    assert [a["key"] for a in run1[1]] == ["stamina"]
    assert [s["key"] for s in run1[2]] == ["budget_level"]


# --- profile: undo ----------------------------------------------------------------


def test_undo_scalar_restores_previous():
    with make_client() as client:
        body = distill(
            client,
            [
                {
                    "key": "budget_level",
                    "value": "economy",
                    "confidence": 0.9,
                    "provenance": "chat",
                }
            ],
        ).json()
        applied_id = body["applied"][0]["applied_id"]
        resp = client.post(f"/api/v1/profile/distill/{applied_id}/undo", headers=DEV)
        assert resp.status_code == 200
        assert resp.json()["profile"]["budget_level"] is None


def test_undo_list_removes_added_items():
    with make_client() as client:
        distill(
            client,
            [
                {
                    "key": "travel_style",
                    "value": "摄影",
                    "confidence": 0.9,
                    "provenance": "chat",
                }
            ],
        )
        body = distill(
            client,
            [
                {
                    "key": "travel_style",
                    "value": ["徒步", "露营"],
                    "confidence": 0.9,
                    "provenance": "chat",
                }
            ],
        ).json()
        applied_id = body["applied"][0]["applied_id"]
        resp = client.post(f"/api/v1/profile/distill/{applied_id}/undo", headers=DEV)
        assert resp.status_code == 200
        assert resp.json()["profile"]["travel_style"] == ["摄影"]


def test_undo_note_removes_entry():
    with make_client() as client:
        body = distill(
            client,
            [
                {
                    "key": "notes",
                    "value": "怕辣",
                    "confidence": 0.9,
                    "provenance": "chat",
                }
            ],
        ).json()
        applied_id = body["applied"][0]["applied_id"]
        resp = client.post(f"/api/v1/profile/distill/{applied_id}/undo", headers=DEV)
        assert resp.json()["profile"]["notes"] == []


def test_undo_unknown_returns_404():
    with make_client() as client:
        resp = client.post("/api/v1/profile/distill/nope/undo", headers=DEV)
        assert resp.status_code == 404
        assert resp.json()["detail"] == "applied_not_found"


def test_undo_then_redistill_applies_again():
    with make_client() as client:
        body = distill(
            client,
            [
                {
                    "key": "stamina",
                    "value": "high",
                    "confidence": 0.9,
                    "provenance": "chat",
                }
            ],
        ).json()
        applied_id = body["applied"][0]["applied_id"]
        client.post(f"/api/v1/profile/distill/{applied_id}/undo", headers=DEV)
        body = distill(
            client,
            [
                {
                    "key": "stamina",
                    "value": "low",
                    "confidence": 0.9,
                    "provenance": "chat",
                }
            ],
        ).json()
        assert body["applied"]  # field stays distillable after undo
        profile = client.get("/api/v1/profile", headers=DEV).json()["profile"]
        assert profile["stamina"] == "low"


# --- links -------------------------------------------------------------------------


def test_links_create_returns_201_pending():
    with make_client() as client:
        resp = client.post(
            "/api/v1/links",
            json={
                "url": "https://example.com/poi/123",
                "source": "user_paste",
                "origin": "chat",
                "itinerary_id": "it-1",
            },
            headers=DEV,
        )
        assert resp.status_code == 201
        record = resp.json()
        assert record["status"] == "pending"
        assert record["url"] == "https://example.com/poi/123"
        assert record["source"] == "user_paste"
        assert record["origin"] == "chat"
        assert record["itinerary_id"] == "it-1"
        assert record["created_at"]


def test_links_list_newest_first():
    with make_client() as client:
        for i in range(3):
            client.post(
                "/api/v1/links",
                json={"url": f"https://example.com/{i}", "source": "user_paste"},
                headers=DEV,
            )
        records = client.get("/api/v1/links", headers=DEV).json()
        assert len(records) == 3
        urls = [r["url"] for r in records]
        assert urls == sorted(urls, reverse=True)  # created_at desc
        assert urls[0] == "https://example.com/2"


def test_links_invalid_url_returns_422():
    with make_client() as client:
        for bad in ("ftp://example.com/x", "not a url", "example.com/x"):
            resp = client.post(
                "/api/v1/links",
                json={"url": bad, "source": "user_paste"},
                headers=DEV,
            )
            assert resp.status_code == 422
            assert resp.json()["detail"] == "invalid_url"


def test_links_invalid_source_returns_422():
    with make_client() as client:
        resp = client.post(
            "/api/v1/links",
            json={"url": "https://example.com", "source": "crawler"},
            headers=DEV,
        )
        assert resp.status_code == 422
        assert resp.json()["detail"] == "invalid_source"


def test_links_reparse_marks_parsed_and_is_idempotent():
    with make_client() as client:
        record = client.post(
            "/api/v1/links",
            json={"url": "https://example.com", "source": "agent_recommend"},
            headers=DEV,
        ).json()
        for _ in range(2):  # second call must not 409/422 — idempotent
            resp = client.post(f"/api/v1/links/{record['id']}/reparse", headers=DEV)
            assert resp.status_code == 200
            assert resp.json()["status"] == "parsed"
        records = client.get("/api/v1/links", headers=DEV).json()
        assert records[0]["status"] == "parsed"


def test_links_reparse_unknown_returns_404():
    with make_client() as client:
        resp = client.post("/api/v1/links/nope/reparse", headers=DEV)
        assert resp.status_code == 404
        assert resp.json()["detail"] == "link_not_found"


# --- isolation + guards ---------------------------------------------------------------


def test_device_isolation_profiles_and_links():
    with make_client() as client:
        client.put("/api/v1/profile", json={"budget_level": "comfort"}, headers=DEV)
        link = client.post(
            "/api/v1/links",
            json={"url": "https://example.com", "source": "user_paste"},
            headers=DEV,
        ).json()
        # device 2 sees neither the profile edits nor the links
        body = client.get("/api/v1/profile", headers=DEV2).json()
        assert body["profile"] == default_profile()
        assert client.get("/api/v1/links", headers=DEV2).json() == []
        resp = client.post(f"/api/v1/links/{link['id']}/reparse", headers=DEV2)
        assert resp.status_code == 404  # foreign id never confirmed


def test_missing_device_id_returns_400():
    with make_client() as client:
        assert client.get("/api/v1/profile").status_code == 400
        assert client.get("/api/v1/profile").json()["detail"] == "missing_device_id"
        assert client.get("/api/v1/links").status_code == 400


# --- wishlist glue (links → trip_items, iron rule 0 single source) --------------------


def test_promote_link_to_wishlist_creates_paste_item():
    with make_client() as client:
        link = client.post(
            "/api/v1/links",
            json={
                "url": "https://example.com/poi/west-lake",
                "source": "user_paste",
                "itinerary_id": "itin-1",
            },
            headers=DEV,
        ).json()
        resp = client.post(
            f"/api/v1/links/{link['id']}/to-wishlist",
            json={"name": "西湖", "city": "杭州"},
            headers=DEV,
        )
        assert resp.status_code == 201
        item = resp.json()
        assert item["name"] == "西湖"
        assert item["city"] == "杭州"
        assert item["status"] == "wishlist"
        assert item["source"] == "paste"
        assert item["itinerary_id"] == "itin-1"
        assert item["note"] == link["url"]


def test_promote_link_defaults_name_to_url_and_404_on_unknown():
    with make_client() as client:
        link = client.post(
            "/api/v1/links",
            json={"url": "https://example.com/x", "source": "user_paste"},
            headers=DEV,
        ).json()
        resp = client.post(
            f"/api/v1/links/{link['id']}/to-wishlist", json={}, headers=DEV
        )
        assert resp.status_code == 201
        assert resp.json()["name"] == "https://example.com/x"
        # unknown id → 404, foreign device → 404
        assert (
            client.post(
                "/api/v1/links/nope/to-wishlist", json={}, headers=DEV
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/api/v1/links/{link['id']}/to-wishlist", json={}, headers=DEV2
            ).status_code
            == 404
        )
