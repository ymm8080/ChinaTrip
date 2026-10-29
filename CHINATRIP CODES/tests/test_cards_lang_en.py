# -*- coding: utf-8 -*-
"""P3 后端文案 EN 化回归（X-Lang: en → L() 选文；zh 默认字节不变）。

覆盖：转链卡片 disclaimer/tag/退改摘要、bookings 退改政策、预约三档降级
注记、行前提醒与误车兜底、天气 404 与 day_weather 读侧反查、付款默认退款
文案与 mock 代订扣款描述、通话退款政策。contextvar 会跨用例泄漏——一律走
lang_en fixture，收尾重置 zh。
"""

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.weather import get_weather_session_factory
from app.api.weather import router as weather_router
from app.config import Settings
from app.services import booking_auto as ba
from app.services.bookings import flight_booking, hotel_booking
from app.services.call_service import CallService
from app.services.call_store import CallStore
from app.services.lang_ctx import set_lang
from app.services.offer_cards import (
    flight_offer_cards,
    hotel_offer_cards,
    train_offer_cards,
)
from app.services.payments import (
    KIND_SAVE_METHOD,
    MockGateway,
    PaymentService,
    PaymentStore,
    default_refund_summary,
)
from app.services.transport_reminders import (
    build_departure_reminders,
    missed_connection_fallback,
)
from app.services.weather_open_meteo import WMO_TEXT, WMO_TEXT_EN, day_text_en

SETTINGS = Settings(alliance_id="", alliance_sid="")


@pytest.fixture
def lang_en():
    set_lang("en")
    yield
    set_lang("zh")


def _has_zh(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


# --- offer_cards / bookings -----------------------------------------------------


def test_offer_cards_flight_en(lang_en):
    body = flight_offer_cards("北京", "上海", "2026-11-20", settings=SETTINGS)
    assert body["disclaimer"] == "*Final price as shown on the destination page*"
    summaries = {c["channel"]: c["refund_summary"] for c in body["cards"]}
    assert "Qunar/Ctrip" in summaries["qunar"]
    assert "Ctrip/Meituan" in summaries["ctrip"]
    assert all(not _has_zh(s) for s in summaries.values())


def test_hotel_cards_same_price_tag_en(lang_en):
    # 与 test_offer_cards 同一确定性同价请求（ctrip == meituan == 365.0）
    body = hotel_offer_cards(
        "北京",
        "故宫",
        lon=116.397,
        lat=39.918,
        checkin="2026-12-25",
        checkout="2026-12-26",
        settings=SETTINGS,
    )
    assert body["same_price_group"] == ["ctrip", "meituan"]
    assert {c["tag"] for c in body["cards"]} == {"Same price"}
    meituan = next(c for c in body["cards"] if c["channel"] == "meituan")
    assert "Meituan checkout page" in meituan["refund_summary"]


def test_train_cards_unified_tag_and_12306_refund_en(lang_en):
    body = asyncio.run(
        train_offer_cards("北京", "上海", "2026-11-20", settings=SETTINGS)
    )
    card = body["cards"][0]
    assert card["channel"] == "12306"
    assert card["tag"] == "Nationwide flat price"
    assert "12306 checkout page" in card["refund_summary"]
    assert "5%" in card["refund_summary"] and "20%" in card["refund_summary"]


def test_bookings_refund_policy_en(lang_en):
    flight = flight_booking("北京", "上海", "2026-11-20")["refund_policy"]
    assert "Ctrip/Meituan" in flight["summary"]
    hotel = hotel_booking(
        "北京",
        "故宫",
        lon=116.397,
        lat=39.918,
        checkin="2026-11-20",
        checkout="2026-11-22",
    )["refund_policy"]
    assert "Ctrip/Meituan" in hotel["summary"]


def test_bookings_refund_policy_zh_default():
    # 无请求语言（contextvar 默认 zh）：字节不变回归
    summary = flight_booking("北京", "上海", "2026-11-20")["refund_policy"]["summary"]
    assert summary == ("退改政策以携程/美团下单页展示为准；建议选「免费取消」房型")


# --- booking_auto -----------------------------------------------------------------


class _NoKeys:
    ctrip_union_api_key = ""
    tongcheng_api_key = ""
    meituan_api_key = ""
    klook_api_key = ""
    tripcom_api_key = ""


class _WithCtripKey(_NoKeys):
    ctrip_union_api_key = "ct"


def test_booking_auto_tier_notes_en(lang_en, monkeypatch):
    monkeypatch.setattr(ba, "get_settings", lambda: _NoKeys())
    tier, note = ba.resolve_tier("L2")
    assert tier == ba.BookingTier.L1
    assert note.startswith("L2 downgraded to L1:")
    assert "Ctrip union" in note and not _has_zh(note)

    monkeypatch.setattr(ba, "get_settings", lambda: _WithCtripKey())
    tier, note = ba.resolve_tier("L3")
    assert tier == ba.BookingTier.L3
    assert note.startswith("L3 standard loop:")
    assert not _has_zh(note)


def test_booking_auto_tier_note_zh_default(monkeypatch):
    monkeypatch.setattr(ba, "get_settings", lambda: _NoKeys())
    _, note = ba.resolve_tier("L2")
    assert note == (
        "L2 降级 L1：库存 provider key 未配置（携程联盟/同程/美团为主力，任一配好即活）"
    )


# --- transport reminders -------------------------------------------------------------


TRAIN_LEG = {
    "type": "train",
    "departure_time": datetime(2026, 11, 20, 9, 0, 0),
    "station_name": "北京南站",
}


def test_departure_reminders_en(lang_en):
    by_kind = {r["kind"]: r["message"] for r in build_departure_reminders(TRAIN_LEG)}
    assert by_kind["heads_up"] == "Departing tomorrow from 北京南站"
    assert by_kind["prepare"] == "Departing in 2 hours from 北京南站"
    assert by_kind["leave_now"] == "Leave now for 北京南站 (45 min buffer)"
    flight_leg = {**TRAIN_LEG, "type": "flight", "station_name": "首都机场T3"}
    assert build_departure_reminders(flight_leg)[2]["message"] == (
        "Leave now for 首都机场T3 (90 min buffer)"
    )


def test_departure_reminders_zh_default():
    by_kind = {r["kind"]: r["message"] for r in build_departure_reminders(TRAIN_LEG)}
    assert by_kind["heads_up"] == "明天从北京南站出发"
    assert by_kind["leave_now"] == "现在出发去北京南站（预留45分钟缓冲）"


def test_missed_connection_notes_en(lang_en):
    flight = asyncio.run(
        missed_connection_fallback(
            {
                "type": "flight",
                "departure_time": datetime(2026, 11, 20, 9, 0, 0),
                "station_name": None,
            },
            train_service=None,
            taxi_deeplink_builder=lambda *a: None,
        )
    )
    assert flight["note"] == (
        "No flight timetable in MVP - rebook or contact your airline; "
        "take a taxi to the airport as a fallback"
    )

    class _EmptyTrainService:
        async def search(self, a, b, d):
            return []

    train = asyncio.run(
        missed_connection_fallback(
            {**TRAIN_LEG, "from_city": "北京", "to_city": "上海"},
            train_service=_EmptyTrainService(),
            taxi_deeplink_builder=lambda *a: None,
        )
    )
    assert train["note"] == "Missed-train rescue is always free"


# --- weather -------------------------------------------------------------------------


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *criteria):
        return self

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def query(self, model):
        return FakeQuery(self.rows)


class FakeFactory:
    def __init__(self, rows):
        self._rows = rows

    def __call__(self):
        return FakeSession(self._rows)


def _row(kind, payload, source="amap"):
    return SimpleNamespace(
        source=source,
        adcode="110000",
        city="北京市",
        kind=kind,
        report_time=None,
        payload=payload,
        fetched_at=datetime(2026, 10, 25, 8, 0, 0),
    )


def _weather_client(rows):
    app = FastAPI()
    app.include_router(weather_router)
    app.dependency_overrides[get_weather_session_factory] = lambda: FakeFactory(rows)
    return TestClient(app)


def test_day_text_en_roundtrip_and_passthrough():
    assert set(WMO_TEXT) == set(WMO_TEXT_EN)  # 两表键集一致（新码必须双写）
    for code, zh in WMO_TEXT.items():
        assert day_text_en(zh) == WMO_TEXT_EN[code]
    assert day_text_en("浮尘") == "浮尘"  # 高德上游独有 zh 透传
    assert day_text_en("") == ""
    assert day_text_en("Sunny") == "Sunny"  # EN 输入幂等


def test_weather_view_en_maps_day_text(lang_en):
    rows = [
        _row("live", {"weather": "雾", "temperature": "18"}),
        _row(
            "forecast",
            {
                "casts": [
                    {"date": "2026-10-26", "day_weather": "晴", "night_weather": "多云"}
                ]
            },
        ),
        _row(
            "forecast14",
            {"casts": [{"date": "2026-11-05", "day_weather": "雷阵雨"}]},
            source="open-meteo",
        ),
    ]
    body = _weather_client(rows).get("/api/weather", params={"city": "北京"}).json()
    assert body["live"]["weather"] == "Fog"
    cast = body["forecast"]["casts"][0]
    assert cast["day_weather"] == "Sunny" and cast["night_weather"] == "Cloudy"
    assert body["forecast14"]["casts"][0]["day_weather"] == "Thunderstorm"


def test_weather_404_details_en(lang_en):
    r = _weather_client([]).get("/api/weather", params={"city": "亚特兰蒂斯"})
    assert r.status_code == 404
    assert r.json()["detail"] == "City not covered: 亚特兰蒂斯"
    r = _weather_client([]).get("/api/weather", params={"city": "北京"})
    assert r.json()["detail"] == "No weather data yet: 北京 (waiting for the fetch job)"


def test_weather_view_zh_default_untouched():
    rows = [
        _row(
            "forecast14",
            {"casts": [{"date": "2026-11-05", "day_weather": "雷阵雨"}]},
            source="open-meteo",
        )
    ]
    body = _weather_client(rows).get("/api/weather", params={"city": "北京"}).json()
    assert body["forecast14"]["casts"][0]["day_weather"] == "雷阵雨"
    r = _weather_client([]).get("/api/weather", params={"city": "亚特兰蒂斯"})
    assert r.json()["detail"] == "未收录城市: 亚特兰蒂斯"


# --- payments ------------------------------------------------------------------


def _checkout(svc, kind, amount):
    return svc.create_checkout(
        device_id="d1",
        username=None,
        kind=kind,
        amount_yuan=amount,
        currency="cny",
        description="",
        refund_summary=None,
        handoff_id=None,
        trip_item_id=None,
        email=None,
        success_url=None,
        cancel_url=None,
    )[0]


def test_payments_en(tmp_path, lang_en):
    svc = PaymentService(
        store=PaymentStore(str(tmp_path / "p.db")), gateway=MockGateway()
    )
    record = _checkout(svc, "pay_now", 10.0)
    assert record.refund_summary.startswith("Cancel anytime before payment")
    assert not _has_zh(record.refund_summary)

    saved = _checkout(svc, KIND_SAVE_METHOD, None)
    svc.confirm_mock(saved.id)
    _, charged = svc.charge_saved(saved.id, 5.0, "")
    assert charged.description == "Concierge charge (mock)"


def test_default_refund_summary_zh_default():
    assert default_refund_summary() == (
        "未支付可随时取消；支付成功后退改以订单页为准，退款请联系客服。"
        "Refunds after payment: contact support; terms per order page."
    )


# --- call ------------------------------------------------------------------------


def _call_service() -> CallService:
    settings = Settings(
        call_provider="mock",
        call_waiting_timeout_seconds=120,
        call_db_url="sqlite:///:memory:",
    )
    return CallService(CallStore(":memory:"), settings)


def test_call_refund_summary_en(lang_en):
    text = _call_service().refund_summary()
    assert "prepaid credits" in text
    assert "{timeout}" not in text and "120 seconds" in text
    assert not _has_zh(text)


def test_call_refund_summary_zh_default():
    text = _call_service().refund_summary()
    assert text.startswith("通话分钟为预付费虚拟权益")
    assert "（120 秒无人接听）" in text
