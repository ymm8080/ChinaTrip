"""weather 服务层测试（FakeSession 离线 + MockTransport，不连真库/不出网）."""

import asyncio
from datetime import datetime

import httpx

from app.models import Itinerary, ItineraryDay, TripItem, WeatherReport
from app.services.amap_client import AmapClient
from app.services.weather import (
    city_to_adcode,
    fetch_and_store,
    parse_report_time,
    trip_cities,
    upsert_weather,
)


class FakeQuery:
    def __init__(self, rows):
        self._rows = rows
        self._kw: dict = {}

    def distinct(self):
        return self

    def all(self):
        return self._rows

    def filter_by(self, **kw):
        self._kw = kw
        return self

    def one_or_none(self):
        for row in self._rows:
            if all(getattr(row, k, None) == v for k, v in self._kw.items()):
                return row
        return None


class FakeSession:
    """内存会话：query(model) 按 model 取预置行，query 链在 FakeQuery 上."""

    def __init__(self, rows_by_model=None):
        self.rows_by_model = rows_by_model or {}
        self.rows = list(self.rows_by_model.get(WeatherReport, []))
        self.added = []
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def query(self, model):
        # query() 实参可能是模型类或 InstrumentedAttribute（如 Itinerary.cities），
        # 统一解析回所属模型类再取预置行。
        target = getattr(model, "class_", model)
        if target is WeatherReport:
            return FakeQuery(self.rows)
        return FakeQuery(self.rows_by_model.get(target, []))

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1
        self.rows.extend(self.added)
        self.added = []


class FakeFactory:
    def __init__(self, session):
        self.session = session

    def __call__(self):
        return self.session


def _amap_handler(request: httpx.Request) -> httpx.Response:
    params = dict(request.url.params)
    if params.get("extensions") == "base":
        return httpx.Response(
            200,
            json={
                "status": "1",
                "info": "OK",
                "lives": [
                    {
                        "province": "北京",
                        "city": "北京市",
                        "adcode": "110000",
                        "weather": "晴",
                        "temperature": "18",
                        "winddirection": "南",
                        "windpower": "1-3",
                        "humidity": "40",
                        "reporttime": "2026-10-23 08:12:36",
                    }
                ],
            },
        )
    return httpx.Response(
        200,
        json={
            "status": "1",
            "info": "OK",
            "forecasts": [
                {
                    "city": "北京市",
                    "adcode": "110000",
                    "province": "北京",
                    "reporttime": "2026-10-23 08:05:11",
                    "casts": [
                        {
                            "date": "2026-10-23",
                            "dayweather": "晴",
                            "nightweather": "多云",
                            "daytemp": "21",
                            "nighttemp": "9",
                            "daywind": "南",
                            "daypower": "1-3",
                            "nightwind": "南",
                            "nightpower": "1-3",
                        },
                        {
                            "date": "2026-10-24",
                            "dayweather": "多云",
                            "nightweather": "阴",
                            "daytemp": "19",
                            "nighttemp": "8",
                            "daywind": "东",
                            "daypower": "1-3",
                            "nightwind": "东",
                            "nightpower": "1-3",
                        },
                    ],
                }
            ],
        },
    )


def _client() -> AmapClient:
    return AmapClient(
        key="test-key",
        transport=httpx.MockTransport(_amap_handler),
    )


# --- 映射与解析 --------------------------------------------------------------


def test_city_to_adcode():
    assert city_to_adcode("北京") == "110000"
    assert city_to_adcode("重庆市") == "500000"  # 「市」后缀容错
    assert city_to_adcode("110000") == "110000"  # adcode 直传
    assert city_to_adcode(" Atlantis ") is None
    assert city_to_adcode("") is None
    assert city_to_adcode(None) is None


def test_parse_report_time():
    assert parse_report_time("2026-10-23 08:12:36") == datetime(2026, 10, 23, 8, 12, 36)
    assert parse_report_time("") is None
    assert parse_report_time("garbage") is None


# --- AmapClient.get_weather 归一化 -------------------------------------------


def test_get_weather_live():
    report = asyncio.run(_client().get_weather("110000", extensions="base"))
    assert report["kind"] == "live"
    assert report["adcode"] == "110000"
    assert report["payload"]["weather"] == "晴"
    assert report["payload"]["temperature"] == "18"


def test_get_weather_forecast():
    report = asyncio.run(_client().get_weather("110000", extensions="all"))
    assert report["kind"] == "forecast"
    casts = report["payload"]["casts"]
    assert len(casts) == 2
    assert casts[0]["date"] == "2026-10-23"
    assert casts[0]["day_temp"] == "21"
    assert casts[1]["night_weather"] == "阴"


def test_get_weather_empty_rows():
    def empty_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "1", "info": "OK"})

    client = AmapClient(key="test-key", transport=httpx.MockTransport(empty_handler))
    assert asyncio.run(client.get_weather("999999")) == {}


# --- upsert latest-wins ------------------------------------------------------


def _report(report_time="2026-10-23 08:12:36", temp="18"):
    return {
        "kind": "live",
        "city": "北京市",
        "adcode": "110000",
        "report_time": report_time,
        "payload": {"weather": "晴", "temperature": temp},
    }


def test_upsert_insert_then_update():
    session = FakeSession()
    assert upsert_weather(session, _report()) == "inserted"
    session.commit()  # commit 由调用方负责（与 fetch_and_store 一致）
    assert len(session.rows) == 1

    row = session.rows[0]
    assert row.city == "北京市"
    assert row.payload["temperature"] == "18"

    # 同键二次写入 → 覆盖，不堆历史
    second = _report(report_time="2026-10-23 11:05:00", temp="22")
    assert upsert_weather(session, second) == "updated"
    assert len(session.rows) == 1
    assert row.payload["temperature"] == "22"
    assert row.report_time == datetime(2026, 10, 23, 11, 5)


def test_upsert_missing_report_time_keeps_none():
    session = FakeSession()
    report = _report()
    report["report_time"] = None
    assert upsert_weather(session, report) == "inserted"
    session.commit()
    assert session.rows[0].report_time is None


# --- fetch_and_store ---------------------------------------------------------


def test_fetch_and_store_stats():
    session = FakeSession()
    stats = asyncio.run(fetch_and_store(FakeFactory(session), _client(), ["北京"]))
    assert stats["cities"] == 1
    assert stats["fetched"] == 2
    assert stats["inserted"] == 2
    assert stats["errors"] == 0
    assert session.commits == 2
    kinds = {r.kind for r in session.rows}
    assert kinds == {"live", "forecast"}


def test_fetch_and_store_skips_unknown_city():
    session = FakeSession()
    stats = asyncio.run(
        fetch_and_store(FakeFactory(session), _client(), ["北京", "亚特兰蒂斯"])
    )
    assert stats["cities"] == 1
    assert stats["skipped"] == 1
    assert stats["fetched"] == 2


# --- trip_cities -------------------------------------------------------------


def test_trip_cities_dedup_and_sort():
    session = FakeSession(
        {
            Itinerary: [(["北京", "西安"],), (["重庆"],)],
            ItineraryDay: [("西安市",), ("北京",)],
            TripItem: [("重庆",), (None,)],
        }
    )
    assert trip_cities(session) == ["北京", "西安", "重庆"]
