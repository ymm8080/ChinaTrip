"""Tests for GET /api/weather + POST /api/weather/sync.

App assembly mirrors tests/test_api_pois.py: fresh app +
dependency_overrides, no real DB. 2026-10-28 起 sync 是纯读表巡检
（从不出网），测试无需 monkeypatch 抓取函数；rows are
SimpleNamespaces shaped like WeatherReport.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import weather as weather_api
from app.api.weather import get_weather_session_factory
from app.api.weather import router as weather_router
from app.services.itinerary import DayPlan, ItineraryPlan
from app.services.itinerary_store import InMemoryItineraryStore, ItineraryRecord
from app.services.trip_items import TripItemService


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


def make_client(rows, store=None, trip_item_svc=None):
    app = FastAPI()
    app.include_router(weather_router)
    app.dependency_overrides[get_weather_session_factory] = lambda: FakeFactory(rows)
    # H5 状态域缺省空内存实现：单测不背真实 SQLite/PG 进程单例
    app.dependency_overrides[weather_api.get_h5_store] = lambda: (
        store if store is not None else InMemoryItineraryStore()
    )
    app.dependency_overrides[weather_api.get_h5_trip_item_service] = lambda: (
        trip_item_svc if trip_item_svc is not None else TripItemService()
    )
    return TestClient(app)


def test_sync_module_has_no_fetchers():
    """纯读表保证（2026-10-28 定稿）：sync 模块不得引用任何抓取设施——
    API 调用只属于每日管线作业（app.jobs.fetch_weather）。"""
    for name in ("fetch_and_store", "fetch_forecast14", "build_map_client"):
        assert not hasattr(weather_api, name)


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


# --- POST /api/weather/sync（纯读表巡检：只回报，从不出网）----------------------


def test_sync_fresh_city_reports_fresh():
    # fetched_at 锚定北京时间今天中午（=UTC 04:00），任何时刻跑都判「新鲜」
    bj_noon = datetime.strptime(weather_api._today_beijing(), "%Y-%m-%d") + timedelta(
        hours=12
    )
    client = make_client([make_row(fetched_at=bj_noon - timedelta(hours=8))])

    resp = client.post("/api/weather/sync", json={"cities": ["北京"]})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["cities"]) == 1
    assert body["cities"][0]["city"] == "北京"
    assert body["cities"][0]["has_data"] is True
    assert body["cities"][0]["fresh"] is True
    assert body["cities"][0]["fetched_at"] is not None


def test_sync_stale_city_reports_without_fetching():
    """隔日数据只如实回报 fresh=False——刷新是每日管线的事，请求路径零 API。"""
    stale_row = make_row(fetched_at=datetime.utcnow() - timedelta(days=3))
    client = make_client([stale_row])

    resp = client.post("/api/weather/sync", json={"cities": ["北京"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["cities"][0]["has_data"] is True
    assert body["cities"][0]["fresh"] is False


def test_sync_new_city_reports_no_data():
    """新行程城市第一次 sync：表里还没有（等每日管线全量班）→ has_data=False，
    不报错也不出网。"""
    client = make_client([])

    resp = client.post("/api/weather/sync", json={"cities": ["北京"]})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["cities"]) == 1
    assert body["cities"][0]["city"] == "北京"
    assert body["cities"][0]["has_data"] is False
    assert body["cities"][0]["fresh"] is False
    assert body["cities"][0]["fetched_at"] is None


def test_sync_unknown_city_silently_skipped():
    client = make_client([])

    resp = client.post("/api/weather/sync", json={"cities": ["亚特兰蒂斯"]})
    assert resp.status_code == 200
    assert resp.json()["cities"] == []


def test_sync_empty_cities_uses_trip_cities():
    # 行程库为空（FakeSession 无预置行 + 空内存状态域）→ 无目标 → 只读返回
    client = make_client([])

    resp = client.post("/api/weather/sync", json={"cities": []})
    assert resp.status_code == 200
    assert resp.json()["cities"] == []


def test_sync_empty_cities_merges_store_cities():
    """PG 三表为空时也要能从 H5 状态域发现行程城市（2026-10-25 根因：
    旧行程都在状态库里，只查 trip_cities 永远为空）。"""
    store = InMemoryItineraryStore()
    store.put(
        ItineraryRecord(
            itinerary_id="it_x",
            owner_device_id="d1",
            plan=ItineraryPlan(
                itinerary_id="it_x",
                cities=["杭州"],
                days=[DayPlan(day=1, base_city="上海市")],
            ),
        )
    )
    svc = TripItemService()
    svc.create("外滩", source="manual", city="上海")
    client = make_client([], store=store, trip_item_svc=svc)

    resp = client.post("/api/weather/sync", json={"cities": []})
    assert resp.status_code == 200
    body = resp.json()
    assert [c["city"] for c in body["cities"]] == ["上海", "杭州"]
    # 表里没有这两城的数据 → 如实回报 has_data=False（等管线，不出网）
    assert all(c["has_data"] is False for c in body["cities"])
