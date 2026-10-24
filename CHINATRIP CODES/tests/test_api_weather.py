"""Tests for GET /api/weather + POST /api/weather/sync.

App assembly mirrors tests/test_api_pois.py: fresh app +
dependency_overrides, no real DB. Fetch functions are monkeypatched at
the app.api.weather namespace so no network happens; rows are
SimpleNamespaces shaped like WeatherReport.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import weather as weather_api
from app.api.weather import get_weather_session_factory
from app.api.weather import router as weather_router


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *criteria):
        return self

    def filter_by(self, **criteria):
        return self

    def distinct(self):
        return self

    def all(self):
        return self.rows

    def one_or_none(self):
        return self.rows[0] if self.rows else None

    def first(self):
        return self.rows[0] if self.rows else None


class FakeSession:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def query(self, model):
        return FakeQuery(self.rows)

    def add(self, row):
        self.rows.append(row)

    def commit(self):
        pass


class FakeFactory:
    def __init__(self, rows):
        self._rows = rows

    def __call__(self):
        return FakeSession(self._rows)


def make_row(**over) -> SimpleNamespace:
    base = dict(
        source="amap",
        adcode="110000",
        city="北京市",
        kind="forecast",
        report_time=datetime(2026, 10, 24, 8, 0, 0),
        payload={"city": "北京市", "adcode": "110000", "casts": []},
        fetched_at=datetime.utcnow(),
    )
    base.update(over)
    return SimpleNamespace(**base)


def make_client(rows):
    app = FastAPI()
    app.include_router(weather_router)
    app.dependency_overrides[get_weather_session_factory] = lambda: FakeFactory(rows)
    return TestClient(app)


def patch_fetchers(monkeypatch, amap_calls, om_calls):
    async def fake_amap(factory, client, cities, **kw):
        amap_calls.extend(cities)
        return {}

    async def fake_om(factory, cities, **kw):
        om_calls.extend(cities)
        return {}

    monkeypatch.setattr(weather_api, "fetch_and_store", fake_amap)
    monkeypatch.setattr(weather_api, "fetch_forecast14", fake_om)
    monkeypatch.setattr(
        weather_api,
        "get_settings",
        lambda: SimpleNamespace(
            amap_api_key="test-key", amap_base_url="http://x", amap_timeout_seconds=1
        ),
    )
    monkeypatch.setattr(weather_api, "AmapClient", lambda **kw: SimpleNamespace())


# --- GET /api/weather ---------------------------------------------------------


def test_get_weather_returns_view():
    client = make_client([make_row()])
    resp = client.get("/api/weather", params={"city": "北京"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["city"] == "北京市"
    assert body["adcode"] == "110000"
    assert body["forecast"] == {"city": "北京市", "adcode": "110000", "casts": []}


def test_get_weather_unknown_city_404():
    client = make_client([])
    resp = client.get("/api/weather", params={"city": "亚特兰蒂斯"})
    assert resp.status_code == 404


# --- POST /api/weather/sync ----------------------------------------------------


def test_sync_fresh_city_skips_refresh(monkeypatch):
    amap_calls, om_calls = [], []
    patch_fetchers(monkeypatch, amap_calls, om_calls)
    # fetched_at 锚定北京时间今天中午（=UTC 04:00），任何时刻跑都判「新鲜」
    bj_noon = datetime.strptime(weather_api._today_beijing(), "%Y-%m-%d") + timedelta(
        hours=12
    )
    client = make_client([make_row(fetched_at=bj_noon - timedelta(hours=8))])

    resp = client.post("/api/weather/sync", json={"cities": ["北京"]})
    assert resp.status_code == 200
    body = resp.json()
    assert amap_calls == [] and om_calls == []  # 新鲜 → 不出网
    assert len(body["cities"]) == 1
    assert body["cities"][0]["city"] == "北京"
    assert body["cities"][0]["refreshed"] is False
    assert body["cities"][0]["fetched_at"] is not None


def test_sync_stale_city_refreshes(monkeypatch):
    amap_calls, om_calls = [], []
    patch_fetchers(monkeypatch, amap_calls, om_calls)
    stale_row = make_row(fetched_at=datetime.utcnow() - timedelta(days=3))
    client = make_client([stale_row])

    resp = client.post("/api/weather/sync", json={"cities": ["北京"]})
    assert resp.status_code == 200
    body = resp.json()
    assert amap_calls == ["北京"]  # 高德 + Open-Meteo 都要刷
    assert om_calls == ["北京"]
    assert body["cities"][0]["refreshed"] is True
    assert body["cities"][0]["fetched_at"] is not None


def test_sync_unknown_city_silently_skipped(monkeypatch):
    amap_calls, om_calls = [], []
    patch_fetchers(monkeypatch, amap_calls, om_calls)
    client = make_client([])

    resp = client.post("/api/weather/sync", json={"cities": ["亚特兰蒂斯"]})
    assert resp.status_code == 200
    assert resp.json()["cities"] == []
    assert amap_calls == [] and om_calls == []


def test_sync_empty_cities_uses_trip_cities(monkeypatch):
    amap_calls, om_calls = [], []
    patch_fetchers(monkeypatch, amap_calls, om_calls)
    # 行程库为空（FakeSession 无预置行）→ 无目标 → 只读返回
    client = make_client([])

    resp = client.post("/api/weather/sync", json={"cities": []})
    assert resp.status_code == 200
    assert resp.json()["cities"] == []
    assert amap_calls == [] and om_calls == []
