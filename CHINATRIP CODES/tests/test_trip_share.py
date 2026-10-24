"""Trip-share: owner toggle + public read-only API + /s/ OG landing."""

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.share as share_mod
from app.api.itineraries import _account_from_auth, get_store
from app.api.share import router as share_router
from app.middleware.ratelimit import RateLimiter
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    TransferItem,
    VisitItem,
)
from app.services.itinerary_store import InMemoryItineraryStore, ItineraryRecord

TOKEN_MIN_ENTROPY_CHARS = 20  # token_urlsafe(16) -> 22 chars


def make_record(
    owner: str = "devA", cities: list[str] | None = None
) -> ItineraryRecord:
    cities = cities or ["北京", "上海"]
    now = datetime.now(timezone.utc)
    visit = VisitItem(
        item_id="v1",
        name="故宫",
        category="sight",
        city="北京",
        location=GeoPoint(lon=116.397, lat=39.918),
        address="景山前街4号",
        opening_hours="08:30-17:00",
        day=1,
        start_time=None,
        end_time=None,
        duration_minutes=120,
        poi_id="poi-internal",
        pinned=True,
    )
    transfer = TransferItem(
        item_id="t1",
        day=1,
        seq=1,
        from_city="北京",
        to_city="上海",
        mode="train",
        train_no="G101",
    )
    plan = ItineraryPlan(
        itinerary_id="it_x1",
        cities=cities,
        days=[DayPlan(day=1, base_city="北京", items=[visit, transfer])],
    )
    return ItineraryRecord(
        itinerary_id="it_x1",
        owner_device_id=owner,
        plan=plan,
        created_at=now,
        updated_at=now,
    )


def make_app(
    record: ItineraryRecord | None = None,
) -> tuple[FastAPI, InMemoryItineraryStore]:
    """Mini app (test_trip_items pattern). _account_from_auth is overridden
    too — its real implementation builds the SQLite account singleton."""
    app = FastAPI()
    app.include_router(share_router)
    store = InMemoryItineraryStore()
    if record is not None:
        store.put(record)
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[_account_from_auth] = lambda: None
    return app, store


@pytest.fixture(autouse=True)
def _fresh_public_limiter():
    share_mod.reset_public_limiter_for_tests()
    yield
    share_mod.reset_public_limiter_for_tests()


# --- owner-side toggle ---------------------------------------------------------


def test_enable_mints_token_and_survives_reenable():
    app, _ = make_app(make_record())
    with TestClient(app) as client:
        first = client.post(
            "/api/v1/itineraries/it_x1/share",
            json={"enabled": True},
            headers={"X-Device-ID": "devA"},
        )
        assert first.status_code == 200
        token = first.json()["share_token"]
        assert len(token) >= TOKEN_MIN_ENTROPY_CHARS
        # 复制链接按钮再次调用：幂等，同 token 不轮换
        second = client.post(
            "/api/v1/itineraries/it_x1/share",
            json={"enabled": True},
            headers={"X-Device-ID": "devA"},
        )
        assert second.json()["share_token"] == token


def test_toggle_requires_device_and_ownership():
    app, _ = make_app(make_record())
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/v1/itineraries/it_x1/share", json={"enabled": True}
            ).status_code
            == 400
        )
        foreign = client.post(
            "/api/v1/itineraries/it_x1/share",
            json={"enabled": True},
            headers={"X-Device-ID": "devB"},
        )
        assert foreign.status_code == 404  # 归属不符一律 404，不做存在性 oracle
        assert foreign.json() == {"detail": "itinerary_not_found"}


def test_disable_then_enable_keeps_same_token():
    app, store = make_app(make_record())
    with TestClient(app) as client:
        h = {"X-Device-ID": "devA"}
        token = client.post(
            "/api/v1/itineraries/it_x1/share", json={"enabled": True}, headers=h
        ).json()["share_token"]
        off = client.post(
            "/api/v1/itineraries/it_x1/share", json={"enabled": False}, headers=h
        )
        assert off.json() == {
            "itinerary_id": "it_x1",
            "share_enabled": False,
            "share_token": None,  # 关闭态不回传 token
        }
        assert store.get("it_x1").share_enabled is False
        again = client.post(
            "/api/v1/itineraries/it_x1/share", json={"enabled": True}, headers=h
        ).json()["share_token"]
        assert again == token


def test_share_fields_roundtrip_legacy_json():
    record = make_record()
    record.share_enabled = True
    record.share_token = "tok"
    # 存量 JSON（无 share 字段）加载 → 默认关闭，写入穿透兼容
    legacy = record.model_dump(exclude={"share_enabled", "share_token"})
    revived = ItineraryRecord.model_validate(legacy)
    assert revived.share_enabled is False
    assert revived.share_token is None


# --- public JSON -----------------------------------------------------------------


def _enable(client) -> str:
    resp = client.post(
        "/api/v1/itineraries/it_x1/share",
        json={"enabled": True},
        headers={"X-Device-ID": "devA"},
    )
    return resp.json()["share_token"]


def test_public_payload_is_whitelisted():
    app, _ = make_app(make_record())
    with TestClient(app) as client:
        token = _enable(client)
        body = client.get(f"/api/v1/public/trips/{token}").json()
    assert body["title"] == "北京 → 上海 · 1天行程"
    assert body["days_count"] == 1 and body["stops_count"] == 1
    day = body["days"][0]
    visit, transfer = day["items"]
    assert visit["kind"] == "visit"
    assert visit["name"] == "故宫" and visit["address"] == "景山前街4号"
    assert visit["location"] == {"lon": 116.397, "lat": 39.918}
    # 白名单之外一字节都不漏：内部 id / 归属 / 钉住标记全无
    for forbidden in (
        "poi_id",
        "item_id",
        "pinned",
        "owner_device_id",
        "owner_account_id",
        "snapshots",
        "working_sync_version",
    ):
        assert forbidden not in str(visit) and forbidden not in str(transfer)
    assert transfer["kind"] == "transfer"
    assert transfer["train_no"] == "G101" and transfer["from_city"] == "北京"


def test_public_404_is_uniform_never_an_oracle():
    app, _ = make_app(make_record())
    with TestClient(app) as client:
        token = _enable(client)
        unknown = client.get("/api/v1/public/trips/nope")
        assert unknown.status_code == 404 and unknown.json() == {"detail": "not_found"}
        client.post(
            "/api/v1/itineraries/it_x1/share",
            json={"enabled": False},
            headers={"X-Device-ID": "devA"},
        )
        disabled = client.get(f"/api/v1/public/trips/{token}")
        assert disabled.status_code == 404 and disabled.json() == {
            "detail": "not_found"
        }


# --- /s/{token} OG landing ---------------------------------------------------------


def test_landing_serves_og_and_escapes():
    app, _ = make_app(make_record(cities=["<script>alert(1)</script>", "上海"]))
    with TestClient(app) as client:
        token = _enable(client)
        resp = client.get(f"/s/{token}")
    assert resp.status_code == 200
    assert resp.headers["X-Robots-Tag"] == "noindex, nofollow"
    html = resp.text
    assert "<script>alert(1)</script>" not in html  # 转义后不可执行
    assert "&lt;script&gt;" in html
    assert 'property="og:title"' in html
    assert f'location.replace("/h5/?share={token}")' in html
    assert 'http-equiv="refresh"' in html  # 无 JS 兜底跳转


def test_landing_404_uniform():
    app, _ = make_app(make_record())
    with TestClient(app) as client:
        token = _enable(client)
        assert client.get("/s/nope").status_code == 404
        client.post(
            "/api/v1/itineraries/it_x1/share",
            json={"enabled": False},
            headers={"X-Device-ID": "devA"},
        )
        assert client.get(f"/s/{token}").status_code == 404


def test_robots_txt_allows_s_blocks_api():
    app, _ = make_app()
    with TestClient(app) as client:
        body = client.get("/robots.txt").text
    assert "Disallow: /api/" in body
    assert "/s/" not in body.split("Disallow")[1]


# --- per-IP tight limiter ----------------------------------------------------------


def test_public_surfaces_rate_limited_per_ip():
    app, _ = make_app(make_record())
    clock = {"t": 1000.0}
    share_mod._limiter_singleton = RateLimiter(
        per_minute=2, per_hour=100, clock=lambda: clock["t"]
    )
    with TestClient(app) as client:
        token = _enable(client)  # toggle 不走 public limiter
        codes = [
            client.get(f"/api/v1/public/trips/{token}").status_code for _ in range(3)
        ]
    assert codes == [200, 200, 429]
