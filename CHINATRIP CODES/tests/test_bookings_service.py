"""Booking handoff service tests (iron rules 22/23 regressions)."""

import asyncio
from urllib.parse import quote

import pytest

from app.services.bookings import flight_booking, hotel_booking, train_booking
from app.services.trains import MockTrainService

DATE = "2026-10-20"


def _assert_no_key_string(value) -> None:
    """铁律回归：任何产出字符串（URL/文案）不得含 'key='。"""
    if isinstance(value, dict):
        for v in value.values():
            _assert_no_key_string(v)
    elif isinstance(value, list):
        for v in value:
            _assert_no_key_string(v)
    elif isinstance(value, str):
        assert "key=" not in value


def test_train_booking_passes_through_mock_timetable():
    result = asyncio.run(
        train_booking("北京", "上海", DATE, train_service=MockTrainService())
    )
    assert [t["train_no"] for t in result["trains"]] == ["G1", "G3", "G5"]
    first = result["trains"][0]
    assert first["from_station"] == "北京南"
    assert first["to_station"] == "上海虹桥"
    assert first["from_city"] == "北京"
    assert first["date"] == DATE
    _assert_no_key_string(result)


def test_train_booking_handoff_url_carries_encoded_cities_and_date():
    result = asyncio.run(
        train_booking("北京", "上海", DATE, train_service=MockTrainService())
    )
    handoff = result["handoff"]
    assert handoff["channel"] == "12306"
    assert handoff["kind"] == "train"
    assert handoff["app_scheme"] == "railway12326://"
    url = handoff["url"]
    assert url.startswith("https://kyfw.12306.cn/otn/leftTicket/init")
    assert "linktypeid=dc" in url
    assert quote("北京", safe="") in url
    assert quote("上海", safe="") in url
    assert f"date={DATE}" in url
    policy = result["refund_policy"]
    assert policy["source"] == "channel_page"
    assert "12306" in policy["summary"]
    assert "以页面实收为准" in policy["summary"]


def test_train_booking_unknown_city_pair_returns_empty_trains_with_handoff():
    result = asyncio.run(
        train_booking("拉萨", "上海", DATE, train_service=MockTrainService())
    )
    assert result["trains"] == []
    assert result["handoff"]["url"].startswith("https://kyfw.12306.cn/otn/")
    assert result["refund_policy"]["summary"]
    _assert_no_key_string(result)


def test_flight_booking_always_empty_with_dual_channel_urls():
    result = flight_booking("北京", "上海", DATE)
    assert result["flights"] == []
    handoff = result["handoff"]
    assert handoff["channel"] == "qunar"
    assert handoff["kind"] == "flight"
    url = handoff["url"]
    assert url.startswith("https://flight.qunar.com/site/onewayList.htm")
    assert f"fromCity={quote('北京', safe='')}" in url
    assert f"toCity={quote('上海', safe='')}" in url
    assert f"fromDate={DATE}" in url
    fallback = handoff["fallback"]
    assert fallback["channel"] == "ctrip"
    assert fallback["url"].startswith("https://flights.ctrip.com/online/list/oneway-")
    assert quote("北京", safe="") in fallback["url"]
    assert quote("上海", safe="") in fallback["url"]
    assert f"depdate={DATE}" in fallback["url"]
    assert result["refund_policy"]["source"] == "channel_page"
    _assert_no_key_string(result)


def test_hotel_booking_composes_url_with_all_params():
    result = hotel_booking(
        "北京",
        "故宫",
        lon=116.397,
        lat=39.918,
        checkin="2026-10-20",
        checkout="2026-10-22",
    )
    handoff = result["handoff"]
    assert handoff["channel"] == "ctrip"
    assert handoff["kind"] == "hotel"
    url = handoff["url"]
    assert url.startswith("https://hotels.ctrip.com/hotels/list")
    assert f"city={quote('北京', safe='')}" in url
    assert "checkin=2026-10-20" in url
    assert "checkout=2026-10-22" in url
    assert f"keyword={quote('故宫', safe='')}" in url
    assert handoff["fallback"] == {
        "channel": "meituan",
        "url": "https://hotel.meituan.com/",
    }
    assert result["near_poi"] == {"name": "故宫", "lon": 116.397, "lat": 39.918}
    summary = result["refund_policy"]["summary"]
    assert result["refund_policy"]["source"] == "channel_page"
    assert "免费取消" in summary
    _assert_no_key_string(result)


def test_hotel_booking_reversed_dates_raise():
    with pytest.raises(ValueError):
        hotel_booking(
            "北京",
            "故宫",
            lon=116.397,
            lat=39.918,
            checkin="2026-10-22",
            checkout="2026-10-20",
        )


def test_hotel_booking_same_day_dates_raise():
    with pytest.raises(ValueError):
        hotel_booking(
            "北京",
            "故宫",
            lon=116.397,
            lat=39.918,
            checkin="2026-10-20",
            checkout="2026-10-20",
        )


def test_hotel_booking_bad_date_format_raise():
    with pytest.raises(ValueError):
        hotel_booking(
            "北京",
            "故宫",
            lon=116.397,
            lat=39.918,
            checkin="2026/10/20",
            checkout="2026-10-22",
        )


def test_hotel_booking_out_of_china_coords_raise():
    with pytest.raises(ValueError):
        hotel_booking(
            "东京",
            "涩谷",
            lon=139.7,
            lat=35.7,
            checkin="2026-10-20",
            checkout="2026-10-22",
        )
    with pytest.raises(ValueError):
        hotel_booking(
            "北京",
            "故宫",
            lon=116.397,
            lat=0.0,
            checkin="2026-10-20",
            checkout="2026-10-22",
        )
