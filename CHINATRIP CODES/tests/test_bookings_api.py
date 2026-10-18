"""Booking handoff API tests (iron rules 22/23 regressions)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.bookings import router as bookings_router


def make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(bookings_router)
    return app


def test_train_returns_trains_with_handoff_and_policy():
    with TestClient(make_app()) as client:
        resp = client.post(
            "/api/v1/bookings/train",
            json={"from_city": "北京", "to_city": "上海", "date": "2026-10-20"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert [t["train_no"] for t in body["trains"]] == ["G1", "G3", "G5"]
    assert body["handoff"]["channel"] == "12306"
    assert body["handoff"]["url"].startswith("https://kyfw.12306.cn/otn/")
    assert body["refund_policy"]["source"] == "channel_page"
    assert "key=" not in resp.text


def test_flight_returns_empty_with_dual_channels():
    with TestClient(make_app()) as client:
        resp = client.post(
            "/api/v1/bookings/flight",
            json={"from_city": "北京", "to_city": "上海", "date": "2026-10-20"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["flights"] == []
    assert body["handoff"]["channel"] == "qunar"
    assert body["handoff"]["fallback"]["channel"] == "ctrip"
    assert body["refund_policy"]["summary"]
    assert "key=" not in resp.text


def test_hotel_returns_ctrip_url_with_dates():
    with TestClient(make_app()) as client:
        resp = client.post(
            "/api/v1/bookings/hotel",
            json={
                "city": "北京",
                "near_poi_name": "故宫",
                "lon": 116.397,
                "lat": 39.918,
                "checkin": "2026-10-20",
                "checkout": "2026-10-22",
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    url = body["handoff"]["url"]
    assert url.startswith("https://hotels.ctrip.com/hotels/list")
    assert "checkin=2026-10-20" in url
    assert "checkout=2026-10-22" in url
    assert body["near_poi"]["name"] == "故宫"
    assert "免费取消" in body["refund_policy"]["summary"]
    assert "key=" not in resp.text


def test_hotel_reversed_dates_returns_422_invalid_booking():
    with TestClient(make_app()) as client:
        resp = client.post(
            "/api/v1/bookings/hotel",
            json={
                "city": "北京",
                "near_poi_name": "故宫",
                "lon": 116.397,
                "lat": 39.918,
                "checkin": "2026-10-22",
                "checkout": "2026-10-20",
            },
        )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "invalid_booking"


def test_hotel_out_of_china_coords_returns_422_invalid_booking():
    with TestClient(make_app()) as client:
        resp = client.post(
            "/api/v1/bookings/hotel",
            json={
                "city": "东京",
                "near_poi_name": "涩谷",
                "lon": 139.7,
                "lat": 35.7,
                "checkin": "2026-10-20",
                "checkout": "2026-10-22",
            },
        )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "invalid_booking"


def test_train_bad_date_format_returns_422():
    with TestClient(make_app()) as client:
        resp = client.post(
            "/api/v1/bookings/train",
            json={"from_city": "北京", "to_city": "上海", "date": "20261020"},
        )
    assert resp.status_code == 422
