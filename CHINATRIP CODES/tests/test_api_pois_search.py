"""Tests for GET /api/pois/search（2026-11-01 行程卡「换景点」下拉）.

App assembly mirrors tests/test_api_pois.py: fresh app +
dependency_overrides over the get_poi_store dependency, no real DB —
the stub store records search_keyword calls and returns canned hits.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.pois import get_poi_store
from app.api.pois import router as pois_router


class StubStore:
    def __init__(self, hits=None, exc=None):
        self.hits = hits or []
        self.exc = exc
        self.calls: list = []

    def search_keyword(self, city, tokens, *, limit=5):
        self.calls.append((city, tokens, limit))
        if self.exc is not None:
            raise self.exc
        return self.hits[:limit]


def make_app(store) -> TestClient:
    app = FastAPI()
    app.dependency_overrides[get_poi_store] = lambda: store
    app.include_router(pois_router)
    return TestClient(app)


HIT = {
    "source_poi_id": "5a_296",
    "name": "秦始皇帝陵博物院（兵马俑）",
    "city": "西安",
    "category": "attraction",
    "tags": ["5a"],
    "address": "西安市临潼区",
    "opening_hours": "08:30-18:00",
    "source": "5a",
    "rating": 4.9,
    "location": (109.278, 34.384),
}


def test_search_passes_engine_params_and_returns_hit():
    store = StubStore([HIT])
    resp = make_app(store).get(
        "/api/pois/search", params={"q": "兵马俑", "city": "西安"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    row = body[0]
    assert row["poi_id"] == "5a_296"
    assert row["name"] == HIT["name"]
    assert row["located"] is True
    assert row["rating"] == 4.9
    assert row["tags"] == ["5a"]
    assert row["opening_hours"] == "08:30-18:00"
    # 引擎同参：city 收窄 + 单 token + 默认 limit 8
    assert store.calls == [("西安", ["兵马俑"], 8)]


def test_search_no_location_row_marks_located_false():
    hit = dict(HIT, location=None, name="骨架行", source_poi_id="sk_1")
    resp = make_app(StubStore([hit])).get(
        "/api/pois/search", params={"q": "骨架", "limit": 3}
    )
    assert resp.status_code == 200
    row = resp.json()[0]
    assert row["located"] is False
    assert row["name"] == "骨架行"


def test_search_blank_name_rows_dropped():
    hit = dict(HIT, name="   ")
    resp = make_app(StubStore([hit])).get("/api/pois/search", params={"q": "x"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_search_missing_q_422():
    resp = make_app(StubStore()).get("/api/pois/search")
    assert resp.status_code == 422


def test_search_store_failure_503():
    resp = make_app(StubStore(exc=RuntimeError("db down"))).get(
        "/api/pois/search", params={"q": "塔"}
    )
    assert resp.status_code == 503
    assert resp.json() == {"detail": "poi store unavailable"}
