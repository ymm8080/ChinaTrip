"""Offer-card center tests (design v2.3 §6.11 candidate card group).

Covers: three-kind card shapes, train single unified-price 12306 card,
price-ascending sort with primary = cheapest, same-price group tag +
stability order, overseas hiding meituan, determinism (same request =
identical response), tracking-param on/off, fixed disclaimer, key-free
responses, 422 validation, and the ±12% deterministic mock price band.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.offers import router as offers_router
from app.config import Settings, get_settings

DISCLAIMER = "*价格以跳转后页面为准*"
TRACKING_SUFFIX = "allianceId=ally-42&sid=sid-42"

OFF_SETTINGS = Settings(alliance_id="", alliance_sid="")
ON_SETTINGS = Settings(alliance_id="ally-42", alliance_sid="sid-42")

CARD_KEYS = {"channel", "price_yuan", "unified_price", "tag", "refund_summary", "url"}
TOP_KEYS = {"kind", "disclaimer", "layout", "primary", "cards", "same_price_group"}


def make_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(offers_router)
    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: settings
    return app


def post_cards(body: dict, settings: Settings | None = None):
    with TestClient(make_app(settings)) as client:
        return client.post("/api/v1/offers/cards", json=body)


def hotel_body(**overrides) -> dict:
    body = {
        "kind": "hotel",
        "city": "北京",
        "near_poi_name": "故宫",
        "lon": 116.397,
        "lat": 39.918,
        "checkin": "2026-11-20",
        "checkout": "2026-11-22",
        "region": "cn",
    }
    body.update(overrides)
    return body


FLIGHT_BODY = {
    "kind": "flight",
    "from_city": "北京",
    "to_city": "上海",
    "date": "2026-11-20",
}
TRAIN_BODY = {
    "kind": "train",
    "from_city": "北京",
    "to_city": "上海",
    "date": "2026-11-20",
}


def _assert_no_key_string(value) -> None:
    """铁律回归：响应任何位置不得出现 'key=' 子串。"""
    if isinstance(value, dict):
        for v in value.values():
            _assert_no_key_string(v)
    elif isinstance(value, list):
        for v in value:
            _assert_no_key_string(v)
    elif isinstance(value, str):
        assert "key=" not in value


def test_hotel_cn_two_cards_shape():
    resp = post_cards(hotel_body(), OFF_SETTINGS)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == TOP_KEYS
    assert body["kind"] == "hotel"
    assert body["layout"] == "primary_plus_expand"
    assert {c["channel"] for c in body["cards"]} == {"ctrip", "meituan"}
    assert body["primary"] == body["cards"][0]
    for card in body["cards"]:
        assert set(card) == CARD_KEYS
        assert isinstance(card["price_yuan"], float) and card["price_yuan"] > 0
        assert card["unified_price"] is False
        assert card["tag"] is None
        assert isinstance(card["refund_summary"], str) and card["refund_summary"]
    urls = {c["channel"]: c["url"] for c in body["cards"]}
    assert urls["ctrip"].startswith("https://hotels.ctrip.com/hotels/list")
    assert "checkin=2026-11-20" in urls["ctrip"]
    assert urls["meituan"].startswith("https://hotel.meituan.com/")
    assert body["same_price_group"] is None


def test_train_single_unified_price_12306_card():
    resp = post_cards(TRAIN_BODY, OFF_SETTINGS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "train"
    assert len(body["cards"]) == 1
    card = body["cards"][0]
    assert card["channel"] == "12306"
    assert card["price_yuan"] is None
    assert card["unified_price"] is True
    assert card["tag"] == "全国统一价"
    assert card["url"].startswith("https://kyfw.12306.cn/otn/leftTicket/init")
    assert "linktypeid=dc" in card["url"]
    assert "date=2026-11-20" in card["url"]
    assert "12306" in card["refund_summary"]
    assert body["primary"] == card
    assert body["same_price_group"] is None


def test_flight_cards_cover_qunar_and_ctrip():
    # 1018 c2ccf08: 去哪儿软404 -> 携程主渠道；渠道标签必须跟 handoff 走，
    # 不得出现「去哪儿卡开携程链」的错标。
    resp = post_cards(FLIGHT_BODY, OFF_SETTINGS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "flight"
    urls = {c["channel"]: c["url"] for c in body["cards"]}
    assert set(urls) == {"qunar", "ctrip"}
    assert urls["ctrip"].startswith("https://flights.ctrip.com/online/list/oneway-")
    assert "depdate=2026-11-20" in urls["ctrip"]
    assert urls["qunar"].startswith("https://flight.qunar.com/site/onewayList.htm")
    assert "fromDate=2026-11-20" in urls["qunar"]


def test_cards_sorted_by_price_ascending_and_primary_is_cheapest():
    for day in (1, 5, 9, 13, 17, 21):
        resp = post_cards(
            hotel_body(checkin=f"2026-12-{day:02d}", checkout=f"2026-12-{day + 1:02d}"),
            OFF_SETTINGS,
        )
        assert resp.status_code == 200
        cards = resp.json()["cards"]
        prices = [c["price_yuan"] for c in cards]
        assert prices == sorted(prices)
        assert resp.json()["primary"]["price_yuan"] == min(prices)


def test_same_price_group_tagged_and_stability_ordered():
    # Deterministic mock: this exact request yields ctrip == meituan == 365.0
    resp = post_cards(
        hotel_body(checkin="2026-12-25", checkout="2026-12-26"), OFF_SETTINGS
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["same_price_group"] == ["ctrip", "meituan"]
    cards = body["cards"]
    assert [c["channel"] for c in cards] == ["ctrip", "meituan"]
    assert [c["price_yuan"] for c in cards] == [365.0, 365.0]
    assert all(c["tag"] == "同价" for c in cards)
    # 同价 → 稳定性序 ctrip > qunar > meituan：携程排前
    assert body["primary"]["channel"] == "ctrip"


def test_overseas_hotel_hides_meituan_single_card():
    resp = post_cards(hotel_body(region="overseas"), OFF_SETTINGS)
    assert resp.status_code == 200
    body = resp.json()
    assert [c["channel"] for c in body["cards"]] == ["ctrip"]
    assert body["primary"]["channel"] == "ctrip"
    assert body["same_price_group"] is None
    assert body["disclaimer"] == DISCLAIMER


def test_deterministic_same_request_identical_response():
    for body in (hotel_body(), FLIGHT_BODY, TRAIN_BODY):
        first = post_cards(body, OFF_SETTINGS)
        second = post_cards(body, OFF_SETTINGS)
        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()


def test_tracking_off_by_default_urls_untouched():
    resp = post_cards(hotel_body(), OFF_SETTINGS)
    assert resp.status_code == 200
    for card in resp.json()["cards"]:
        assert "allianceId" not in card["url"]
        assert "&sid=" not in card["url"]


def test_tracking_on_appends_alliance_params_to_all_urls():
    for body in (hotel_body(), FLIGHT_BODY, TRAIN_BODY):
        resp = post_cards(body, ON_SETTINGS)
        assert resp.status_code == 200
        for card in resp.json()["cards"]:
            assert card["url"].endswith(TRACKING_SUFFIX)
    hotel_urls = {
        c["channel"]: c["url"]
        for c in post_cards(hotel_body(), ON_SETTINGS).json()["cards"]
    }
    # bare meituan base URL has no '?' yet — separator must switch to '?'
    assert hotel_urls["meituan"] == f"https://hotel.meituan.com/?{TRACKING_SUFFIX}"
    assert hotel_urls["ctrip"].startswith("https://hotels.ctrip.com/hotels/list?")


def test_disclaimer_present_for_all_kinds():
    for body, kind in (
        (hotel_body(), "hotel"),
        (FLIGHT_BODY, "flight"),
        (TRAIN_BODY, "train"),
    ):
        resp = post_cards(body, OFF_SETTINGS)
        assert resp.status_code == 200
        assert resp.json()["disclaimer"] == DISCLAIMER
        assert resp.json()["kind"] == kind


def test_no_key_substring_and_no_commission_fields_anywhere():
    for body in (hotel_body(), FLIGHT_BODY, TRAIN_BODY):
        resp = post_cards(body, ON_SETTINGS)
        assert resp.status_code == 200
        payload = resp.json()
        _assert_no_key_string(payload)
        assert "key=" not in resp.text
        for card in payload["cards"]:
            # 佣金字段不存在：卡片键集是封闭白名单
            assert set(card) == CARD_KEYS
            assert "commission" not in card["channel"].lower()


def test_hotel_out_of_china_coords_returns_422_invalid_booking():
    resp = post_cards(
        hotel_body(lon=139.7, lat=35.7, city="东京", near_poi_name="涩谷"), OFF_SETTINGS
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "invalid_booking"


def test_hotel_reversed_dates_returns_422_invalid_booking():
    resp = post_cards(
        hotel_body(checkin="2026-11-22", checkout="2026-11-20"), OFF_SETTINGS
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "invalid_booking"


def test_unknown_kind_returns_422():
    resp = post_cards(
        {"kind": "bus", "from_city": "北京", "to_city": "上海", "date": "2026-11-20"}
    )
    assert resp.status_code == 422


def test_mock_prices_within_12_percent_band():
    hotel_lo, hotel_hi = 350.0 * 0.88, 350.0 * 1.12
    for day in (1, 5, 9, 13, 17, 21):
        resp = post_cards(
            hotel_body(checkin=f"2026-12-{day:02d}", checkout=f"2026-12-{day + 1:02d}"),
            OFF_SETTINGS,
        )
        for card in resp.json()["cards"]:
            assert hotel_lo <= card["price_yuan"] <= hotel_hi
    flight_lo, flight_hi = 760.0 * 0.88, 760.0 * 1.12
    for day in (1, 5, 9, 13, 17, 21):
        resp = post_cards(
            {
                "kind": "flight",
                "from_city": "北京",
                "to_city": "上海",
                "date": f"2026-12-{day:02d}",
            },
            OFF_SETTINGS,
        )
        for card in resp.json()["cards"]:
            assert flight_lo <= card["price_yuan"] <= flight_hi
