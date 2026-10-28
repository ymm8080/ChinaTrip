"""weather 服务层测试（FakeSession 离线 + MockTransport，不连真库/不出网）."""

import asyncio
from datetime import datetime, timedelta

import httpx

from app.models import Itinerary, ItineraryDay, TripItem, WeatherReport
from app.services.amap_client import AmapClient
from app.services.itinerary import DayPlan, ItineraryPlan
from app.services.itinerary_store import ItineraryRecord
from app.services.weather import (
    CITY_ADCODES,
    city_to_adcode,
    fetch_and_store,
    parse_report_time,
    store_cities,
    trip_cities,
    upsert_weather,
)
from app.services.weather_open_meteo import (
    CITY_COORDS,
    FORECAST14_KIND,
    OPEN_METEO_SOURCE,
    STALE_DAYS,
    fetch_forecast14,
    normalize_daily,
    purge_stale,
    wmo_text,
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
    assert city_to_adcode("SHANGHAI") == "310000"  # 英文别名归一(2026-10-28)
    assert city_to_adcode("shanghai") == "310000"
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
    assert row.payload["temperature_f"] == "64"  # 18×9/5+32=64.4→64
    assert row.fetched_at is not None

    # 同键二次写入 → 覆盖，不堆历史
    second = _report(report_time="2026-10-23 11:05:00", temp="22")
    assert upsert_weather(session, second) == "updated"
    assert len(session.rows) == 1
    assert row.payload["temperature"] == "22"
    assert row.report_time == datetime(2026, 10, 23, 11, 5)


def test_upsert_refreshes_fetched_at_on_update():
    session = FakeSession()
    assert upsert_weather(session, _report()) == "inserted"
    session.commit()
    row = session.rows[0]
    # 模拟旧行：上次刷新是 3 天前 → 本次更新必须盖新时间戳
    row.fetched_at = datetime.utcnow() - timedelta(days=3)

    assert upsert_weather(session, _report(temp="22")) == "updated"
    assert row.fetched_at > datetime.utcnow() - timedelta(minutes=1)


def test_upsert_adds_fahrenheit_to_casts_and_live():
    session = FakeSession()
    report = _report()
    report["payload"]["casts"] = [
        {"day_temp": "17", "night_temp": "10"},
        {"day_temp": "12", "night_temp": "9"},
    ]
    upsert_weather(session, report)
    session.commit()
    payload = session.rows[0].payload
    assert payload["casts"][0]["day_temp_f"] == "63"  # 17×9/5+32=62.6→63
    assert payload["casts"][0]["night_temp_f"] == "50"
    assert payload["casts"][1]["day_temp_f"] == "54"  # 12→53.6→54
    assert payload["casts"][1]["night_temp_f"] == "48"  # 9→48.2→48


def test_upsert_fahrenheit_skips_non_numeric():
    session = FakeSession()
    report = _report(temp="")
    report["payload"]["casts"] = [{"day_temp": "n/a", "night_temp": None}]
    upsert_weather(session, report)
    session.commit()
    payload = session.rows[0].payload
    assert "temperature_f" not in payload
    assert "day_temp_f" not in payload["casts"][0]
    assert "night_temp_f" not in payload["casts"][0]


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


# --- store_cities（H5 状态域城市发现）----------------------------------------


class FakeStore:
    """ItineraryStore 的城市发现最小面：list_all()。"""

    def __init__(self, records):
        self._records = records

    def list_all(self):
        return self._records


class FakeTripItemSvc:
    def __init__(self, groups):
        self._groups = groups

    def list_groups(self, itinerary_id=None):
        return self._groups


def _it_record(cities, base_cities):
    return ItineraryRecord(
        itinerary_id="it_test",
        owner_device_id="d1",
        plan=ItineraryPlan(
            itinerary_id="it_test",
            cities=cities,
            days=[DayPlan(day=i + 1, base_city=b) for i, b in enumerate(base_cities)],
        ),
    )


def test_store_cities_merges_records_and_items():
    """旧行程都在状态库、PG 三表为空——只查 trip_cities 永远为空
    （2026-10-25 排障）。store 侧 plan.cities + days[].base_city，条目侧
    list_groups(None) 各组 city，去「市」后缀去重。"""
    store = FakeStore(
        [
            _it_record(["北京", "西安"], ["北京市", "西安"]),
            _it_record(["上海"], ["杭州"]),
        ]
    )
    svc = FakeTripItemSvc(
        {
            "bookings": [{"city": "苏州"}],
            "wishlist": [{"city": "重庆市"}, {"city": None}],
            "scheduled": [],
            "unwanted": [{"city": "成都"}],
        }
    )
    assert store_cities(store, svc) == [
        "上海",
        "北京",
        "成都",
        "杭州",
        "苏州",
        "西安",
        "重庆",
    ]


# --- fetch_weather 管线抓取范围（2026-10-28 定稿：默认全量 40 城）--------------


def test_resolve_targets_defaults_to_all_cities():
    """每日一班全量 40 城：新行程城市开站第一次 /sync 就有隔夜表数据，
    不再有「先有行程后补数据」的空窗（管线是唯一连天气 API 的地方）。"""
    from app.jobs.fetch_weather import resolve_targets

    targets = resolve_targets()
    assert sorted(targets) == sorted(CITY_ADCODES)
    assert len(targets) == 40


def test_resolve_targets_explicit_cities_passthrough():
    from app.jobs.fetch_weather import resolve_targets

    assert resolve_targets(cities=["北京", "上海"]) == ["北京", "上海"]


# --- Open-Meteo 14 天预报（TREK 双轨第二源）-----------------------------------


def test_wmo_text_mapping():
    assert wmo_text(0) == "晴"
    assert wmo_text(3) == "阴"
    assert wmo_text(61) == "小雨"
    assert wmo_text(95) == "雷阵雨"
    assert wmo_text(75) == "大雪"
    assert wmo_text(999) == ""
    assert wmo_text(None) == ""


def test_normalize_daily_same_shape_as_amap():
    data = {
        "daily": {
            "time": ["2026-10-24", "2026-11-06"],
            "weather_code": [61, 0],
            "temperature_2m_max": [17.26, 8.0],
            "temperature_2m_min": [8.7, 0.4],
        }
    }
    report = normalize_daily("北京", "110000", data)
    assert report["kind"] == FORECAST14_KIND
    casts = report["payload"]["casts"]
    assert len(casts) == 2
    assert casts[0] == {
        "date": "2026-10-24",
        "day_weather": "小雨",
        "day_temp": "17",  # 四舍五入，与高德整数字符串同构
        "night_temp": "9",
    }
    assert casts[1]["day_weather"] == "晴"


def test_city_coords_cover_all_40():
    from app.services.weather import CITY_ADCODES

    assert set(CITY_COORDS) == set(CITY_ADCODES)
    assert all(len(v) == 2 for v in CITY_COORDS.values())


def _om_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "daily": {
                "time": ["2026-10-24", "2026-11-06"],
                "weather_code": [2, 95],
                "temperature_2m_max": [17.2, 14.0],
                "temperature_2m_min": [8.7, 3.0],
            }
        },
    )


def test_fetch_forecast14_stats():
    session = FakeSession()
    transport = httpx.MockTransport(_om_handler)

    async def run(cities):
        client = httpx.AsyncClient(transport=transport)  # 服务内 async with 会关闭它
        return await fetch_forecast14(FakeFactory(session), cities, client=client)

    stats = asyncio.run(run(["北京", "亚特兰蒂斯"]))
    assert stats["cities"] == 1
    assert stats["fetched"] == 1
    assert stats["inserted"] == 1
    assert stats["skipped"] == 1
    assert stats["errors"] == 0
    row = session.rows[0]
    assert row.source == OPEN_METEO_SOURCE
    assert row.kind == FORECAST14_KIND
    assert len(row.payload["casts"]) == 2


def test_fetch_forecast14_upsert_updates_existing():
    session = FakeSession()
    transport = httpx.MockTransport(_om_handler)

    async def run():
        client = httpx.AsyncClient(transport=transport)
        return await fetch_forecast14(FakeFactory(session), ["北京"], client=client)

    asyncio.run(run())
    stats = asyncio.run(run())
    assert stats["updated"] == 1
    assert len(session.rows) == 1  # latest-wins 不堆历史


class ExecSession(FakeSession):
    """补 execute()（purge_stale 走 delete 语句）。"""

    def __init__(self, *a, **kw):
        super().__init__(*a)
        self.executed = []

    def execute(self, stmt):
        self.executed.append(stmt)

        class _R:
            rowcount = 3

        return _R()


def test_purge_stale_deletes_old_rows():
    assert STALE_DAYS == 7  # 用户口径：旧记录一周前删
    session = ExecSession()
    deleted = asyncio.run(purge_stale(FakeFactory(session), days=7))
    assert deleted == 3
    assert len(session.executed) == 1
