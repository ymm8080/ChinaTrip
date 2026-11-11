"""Tests for POST /api/pois/photos/fetch + /photos/report-dead (F2/F4).

App assembly mirrors tests/test_api_pois.py: fresh app +
dependency_overrides, no real DB. The fetch chain is monkeypatched at
the api module boundary (fetch_photo_chain / get_settings) so tests
exercise the endpoint semantics — cooldown stamping, fill-empty-only,
failure logging — not the vendor clients themselves.
"""

import logging
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.pois import get_poi_session_factory
from app.api.pois import router as pois_router

POI_UUID = uuid.UUID("11111111-1111-1111-1111-111111111111")
NOW = datetime.now()


def make_row(**over) -> SimpleNamespace:
    base = dict(
        id=POI_UUID,
        source="amap",
        source_poi_id="B001234",
        status="active",
        city="重庆市",
        name_zh="洪崖洞",
        photos=None,
        photos_source=None,
        photos_fetched_at=None,
        photos_fetch_fail=0,
    )
    base.update(over)
    return SimpleNamespace(**base)


class FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *a, **k):
        return self

    def first(self):
        return self._rows[0] if self._rows else None


class FakeSession:
    def __init__(self, rows):
        self._rows = rows
        self.commits = 0

    def query(self, *a, **k):
        return FakeQuery(self._rows)

    def get(self, model, key):
        for row in self._rows:
            if row.id == key:
                return row
        return None

    def commit(self):
        self.commits += 1

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def make_app(session) -> TestClient:
    app = FastAPI()
    app.dependency_overrides[get_poi_session_factory] = lambda: lambda: session
    app.include_router(pois_router)
    return TestClient(app)


@pytest.fixture
def chain_spy(monkeypatch):
    """Patch the chain at the api boundary; returns (calls, setter)."""
    calls = []
    state = {"result": (None, None), "exc": None}

    async def fake_chain(row, *, amap):
        calls.append(row)
        if state["exc"] is not None:
            raise state["exc"]
        return state["result"]

    monkeypatch.setattr("app.api.pois.fetch_photo_chain", fake_chain)

    class _Settings:
        amap_api_key = ""

    monkeypatch.setattr("app.api.pois.get_settings", lambda: _Settings())
    return calls, state


# --- fetch: 已有图 / 冷却 -------------------------------------------------------


def test_fetch_returns_existing_photos_without_chain_call(chain_spy):
    calls, _ = chain_spy
    photos = [{"title": "夜景", "url": "https://img.example/h.jpg"}]
    session = FakeSession([make_row(photos=photos, photos_source="amap")])
    resp = make_app(session).post(
        "/api/pois/photos/fetch", json={"city": "重庆", "name": "洪崖洞"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["fetched"] is False
    assert body["photos"] == photos
    assert body["photos_source"] == "amap"
    assert calls == []
    assert session.commits == 0


def test_fetch_within_cooldown_returns_store_value_no_external_call(chain_spy):
    calls, _ = chain_spy
    session = FakeSession([make_row(photos_fetched_at=NOW - timedelta(hours=2))])
    resp = make_app(session).post(
        "/api/pois/photos/fetch", json={"city": "重庆", "name": "洪崖洞"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["fetched"] is False
    assert body["photos"] == []
    assert calls == []
    assert session.commits == 0


# --- fetch: 真回源（成功 / 拉空 / 异常）----------------------------------------


def test_fetch_success_fills_photos_and_source(chain_spy):
    calls, state = chain_spy
    state["result"] = (
        [{"title": "", "url": "https://img.example/new.jpg"}],
        "amap",
    )
    session = FakeSession([make_row()])
    resp = make_app(session).post(
        "/api/pois/photos/fetch", json={"city": "重庆", "name": "洪崖洞"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["fetched"] is True
    assert body["photos_source"] == "amap"
    assert len(calls) == 1
    assert session.commits == 1
    row = session._rows[0]
    assert row.photos == [{"title": "", "url": "https://img.example/new.jpg"}]
    assert row.photos_source == "amap"
    # 尝试即落戳（冷却键）
    assert row.photos_fetched_at is not None


def test_fetch_empty_result_stamps_cooldown_but_fills_nothing(chain_spy):
    calls, _ = chain_spy
    session = FakeSession([make_row()])
    resp = make_app(session).post(
        "/api/pois/photos/fetch", json={"city": "重庆", "name": "洪崖洞"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["fetched"] is False
    assert body["photos"] == []
    row = session._rows[0]
    # 只填空铁律：拉不到不写 photos/photos_source；但 fetched_at 必落
    assert row.photos is None
    assert row.photos_source is None
    assert row.photos_fetched_at is not None


def test_fetch_chain_failure_returns_empty_and_leaves_warning_log(chain_spy, caplog):
    calls, state = chain_spy
    state["exc"] = RuntimeError("amap quota")
    session = FakeSession([make_row()])
    with caplog.at_level(logging.WARNING, logger="app.api.pois"):
        resp = make_app(session).post(
            "/api/pois/photos/fetch", json={"city": "重庆", "name": "洪崖洞"}
        )
    assert resp.status_code == 200
    assert resp.json() == {"photos": [], "photos_source": None, "fetched": False}
    row = session._rows[0]
    assert row.photos is None
    assert row.photos_fetched_at is not None
    # 失败必须留日志（10-25 立规）
    assert any("chain failed" in r.message for r in caplog.records)


def test_fetch_unknown_poi_returns_404(chain_spy):
    session = FakeSession([])
    resp = make_app(session).post(
        "/api/pois/photos/fetch", json={"city": "重庆", "name": "不存在景点"}
    )
    assert resp.status_code == 404


# --- report-dead ----------------------------------------------------------------


def test_report_dead_increments_fail_counter():
    session = FakeSession([make_row(photos_fetch_fail=1)])
    resp = make_app(session).post(
        "/api/pois/photos/report-dead", json={"poi_id": str(POI_UUID)}
    )
    assert resp.status_code == 204
    assert session._rows[0].photos_fetch_fail == 2
    assert session.commits == 1


def test_report_dead_unknown_poi_silently_204_with_warning(caplog):
    session = FakeSession([])
    with caplog.at_level(logging.WARNING, logger="app.api.pois"):
        resp = make_app(session).post(
            "/api/pois/photos/report-dead", json={"poi_id": str(POI_UUID)}
        )
    assert resp.status_code == 204
    assert any("unknown poi_id" in r.message for r in caplog.records)


def test_report_dead_bad_uuid_silently_204_with_warning(caplog):
    session = FakeSession([make_row()])
    with caplog.at_level(logging.WARNING, logger="app.api.pois"):
        resp = make_app(session).post(
            "/api/pois/photos/report-dead", json={"poi_id": "not-a-uuid"}
        )
    assert resp.status_code == 204
    assert session.commits == 0
    assert any("bad poi_id" in r.message for r in caplog.records)
