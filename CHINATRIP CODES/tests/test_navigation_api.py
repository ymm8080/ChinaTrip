from datetime import datetime, timedelta

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.amap import get_amap_client
from app.api.navigation import router as navi_router
from app.config import Settings, get_settings
from app.services.amap_client import AmapClient

API_KEY = "test-key-123"
BASE_URL = "https://restapi.amap.test/v3"

WALKING_BODY = {
    "status": "1",
    "info": "OK",
    "infocode": "10000",
    "route": {
        "paths": [
            {
                "distance": "1500",
                "duration": "1200",
                "steps": [
                    {
                        "instruction": "沿长安街向东步行100米右转",
                        "road": "长安街",
                        "distance": "100",
                        "orientation": "东",
                        "polyline": "116.397428,39.90923;116.398428,39.90923",
                    },
                    {
                        "instruction": "向南步行到达",
                        "road": "广场东侧路",
                        "distance": "1400",
                        "orientation": "南",
                        "polyline": "116.398428,39.90923;116.398428,39.89685",
                    },
                ],
            }
        ]
    },
}

WALKING_EMPTY_BODY = {"status": "1", "info": "OK", "infocode": "10000", "route": {}}

TRANSIT_BODY = {
    "status": "1",
    "info": "OK",
    "infocode": "10000",
    "route": {
        "transits": [
            {
                "cost": "4",
                "duration": "1500",
                "walking_distance": "600",
                "segments": [
                    {
                        "walking": {"distance": "600", "duration": "480", "steps": []},
                        "bus": {
                            "buslines": [
                                {
                                    "name": "地铁1号线",
                                    "type": "地铁",
                                    "departure_stop": {"name": "天安门东"},
                                    "arrival_stop": {"name": "王府井"},
                                    "via_num": "2",
                                    "departure_time": "08:00:00",
                                }
                            ]
                        },
                    }
                ],
            },
            {
                "cost": "2",
                "duration": "1800",
                "walking_distance": "300",
                "segments": [
                    {
                        "bus": {
                            "buslines": [
                                {
                                    "name": "观光1路",
                                    "type": "普通公交",
                                    "departure_stop": {"name": "前门"},
                                    "arrival_stop": {"name": "王府井"},
                                    "via_num": "5",
                                }
                            ]
                        }
                    }
                ],
            },
        ]
    },
}

ERROR_BODY = {"status": "0", "info": "INVALID_USER_KEY", "infocode": "10001"}


def make_settings(api_key: str = API_KEY) -> Settings:
    return Settings(
        amap_api_key=api_key,
        amap_base_url=BASE_URL,
        amap_timeout_seconds=1.0,
    )


def make_app(handler=None, api_key: str = API_KEY) -> FastAPI:
    app = FastAPI()
    app.include_router(navi_router)
    settings = make_settings(api_key)
    app.dependency_overrides[get_settings] = lambda: settings
    if handler is not None:
        amap = AmapClient(
            key=API_KEY,
            base_url=BASE_URL,
            timeout_seconds=1.0,
            transport=httpx.MockTransport(handler),
        )
        app.dependency_overrides[get_amap_client] = lambda: amap
    return app


def ok_handler(body: dict):
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=body)

    return handler, captured


def timeout_handler():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    return handler


ORIGIN = {"lon": 116.397428, "lat": 39.90923}
DEST = {"lon": 116.410, "lat": 39.912}


def test_walking_success_returns_steps_and_polyline():
    handler, captured = ok_handler(WALKING_BODY)
    with TestClient(make_app(handler)) as client:
        resp = client.post(
            "/api/v1/nav/walking", json={"origin": ORIGIN, "destination": DEST}
        )
    assert resp.status_code == 200
    route = resp.json()["route"]
    assert route["distance_m"] == 1500
    assert len(route["steps"]) == 2
    assert route["steps"][0]["road"] == "长安街"
    assert len(route["polyline"]) == 4
    sent = captured[0].url.params
    assert str(sent["origin"]).startswith("116.397428,")
    assert str(sent["destination"]).startswith("116.410")


def test_walking_same_point_returns_empty_route():
    handler, _ = ok_handler(WALKING_EMPTY_BODY)
    with TestClient(make_app(handler)) as client:
        resp = client.post(
            "/api/v1/nav/walking", json={"origin": ORIGIN, "destination": ORIGIN}
        )
    assert resp.status_code == 200
    assert resp.json()["route"]["steps"] == []


def test_walking_amap_error_returns_502():
    handler, _ = ok_handler(ERROR_BODY)
    with TestClient(make_app(handler)) as client:
        resp = client.post(
            "/api/v1/nav/walking", json={"origin": ORIGIN, "destination": DEST}
        )
    assert resp.status_code == 502
    assert resp.json()["detail"] == "amap_error"


def test_walking_timeout_returns_504():
    with TestClient(make_app(timeout_handler())) as client:
        resp = client.post(
            "/api/v1/nav/walking", json={"origin": ORIGIN, "destination": DEST}
        )
    assert resp.status_code == 504


def test_walking_not_configured_returns_503():
    with TestClient(make_app(api_key="")) as client:
        resp = client.post(
            "/api/v1/nav/walking", json={"origin": ORIGIN, "destination": DEST}
        )
    assert resp.status_code == 503


def test_transit_success_normalizes_plans():
    handler, captured = ok_handler(TRANSIT_BODY)
    with TestClient(make_app(handler)) as client:
        resp = client.post(
            "/api/v1/nav/transit",
            json={"origin": ORIGIN, "destination": DEST, "city": "北京"},
        )
    assert resp.status_code == 200
    plans = resp.json()["plans"]
    assert len(plans) == 2
    assert plans[0]["cost_yuan"] == 4.0
    ride = plans[0]["segments"][0]["rides"][0]
    assert ride["name"] == "地铁1号线"
    assert ride["via_stops"] == 2
    sent = captured[0].url.params
    assert sent["city"] == "北京"


def test_deeplink_taxi_composes_keyless_urls():
    with TestClient(make_app()) as client:
        resp = client.post(
            "/api/v1/nav/deeplink",
            json={
                "mode": "taxi",
                "destination": {"name": "北京南站", "lon": 116.378, "lat": 39.865},
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["app_deeplink"].startswith("amapuri://drive/taxi/")
    assert "key=" not in resp.text


def test_deeplink_driving_includes_fallbacks():
    with TestClient(make_app()) as client:
        resp = client.post(
            "/api/v1/nav/deeplink",
            json={
                "mode": "driving",
                "destination": {"name": "故宫", "lon": 116.397, "lat": 39.918},
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["app_deeplink"].startswith("amapuri://route/plan/")
    assert body["web_fallback"].startswith("https://uri.amap.com/navigation")
    assert body["ios_alternative"].startswith("https://maps.apple.com/")
    assert "key=" not in resp.text


def test_deeplink_out_of_range_coords_returns_422():
    with TestClient(make_app()) as client:
        resp = client.post(
            "/api/v1/nav/deeplink",
            json={
                "mode": "taxi",
                "destination": {"name": "x", "lon": 200.0, "lat": 39.0},
            },
        )
    assert resp.status_code == 422


def test_deeplink_bad_mode_returns_422():
    with TestClient(make_app()) as client:
        resp = client.post(
            "/api/v1/nav/deeplink",
            json={
                "mode": "boat",
                "destination": {"name": "x", "lon": 116.0, "lat": 39.0},
            },
        )
    assert resp.status_code == 422


def test_transport_reminders_train_returns_three_tiers():
    leg = {
        "type": "train",
        "departure_time": (datetime.now() + timedelta(days=2)).isoformat(),
        "station_name": "北京南",
        "station_location": {"lon": 116.378, "lat": 39.865},
    }
    with TestClient(make_app()) as client:
        resp = client.post("/api/v1/nav/transport-reminders", json=leg)
    assert resp.status_code == 200
    reminders = resp.json()["reminders"]
    kinds = [r["kind"] for r in reminders]
    assert kinds == ["heads_up", "prepare", "leave_now"]
    ats = [r["at"] for r in reminders]
    assert ats == sorted(ats)


def test_transport_reminders_flight_uses_longer_buffer():
    leg = {
        "type": "flight",
        "departure_time": (datetime.now() + timedelta(days=2)).isoformat(),
        "station_name": "首都机场T3",
    }
    with TestClient(make_app()) as client:
        resp = client.post("/api/v1/nav/transport-reminders", json=leg)
    assert resp.status_code == 200
    reminders = resp.json()["reminders"]
    assert len(reminders) == 3
    leave_now = reminders[-1]
    assert "90" in leave_now["message"]


def test_transport_reminders_bad_type_returns_422():
    leg = {
        "type": "boat",
        "departure_time": (datetime.now() + timedelta(days=2)).isoformat(),
        "station_name": "x",
    }
    with TestClient(make_app()) as client:
        resp = client.post("/api/v1/nav/transport-reminders", json=leg)
    assert resp.status_code == 422


def test_missed_connection_train_returns_contract_shape():
    leg = {
        "type": "train",
        "departure_time": (datetime.now() - timedelta(hours=1)).isoformat(),
        "station_name": "北京南",
        "station_location": {"lon": 116.378, "lat": 39.865},
        "from_city": "北京",
        "to_city": "上海",
        "date": "2026-10-18",
    }
    with TestClient(make_app()) as client:
        resp = client.post("/api/v1/nav/missed-connection", json=leg)
    assert resp.status_code == 200
    body = resp.json()
    assert body["leg_type"] == "train"
    assert isinstance(body["next_departures"], list)
    assert body["note"]
    if body["taxi"] is not None:
        assert body["taxi"]["app_deeplink"].startswith("amapuri://drive/taxi/")
    assert "key=" not in resp.text


def test_missed_connection_flight_has_no_departures():
    leg = {
        "type": "flight",
        "departure_time": (datetime.now() - timedelta(hours=1)).isoformat(),
        "station_name": "首都机场T3",
        "station_location": {"lon": 116.6, "lat": 40.08},
    }
    with TestClient(make_app()) as client:
        resp = client.post("/api/v1/nav/missed-connection", json=leg)
    assert resp.status_code == 200
    body = resp.json()
    assert body["leg_type"] == "flight"
    assert body["next_departures"] == []
    assert "航班" in body["note"]


def test_missed_connection_route_is_async_importable():
    # guard: router module must import cleanly with all five endpoints wired
    paths = {route.path for route in navi_router.routes}
    assert {
        "/api/v1/nav/walking",
        "/api/v1/nav/transit",
        "/api/v1/nav/deeplink",
        "/api/v1/nav/transport-reminders",
        "/api/v1/nav/missed-connection",
    } <= paths
