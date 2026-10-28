"""互动闭环端点/存储测试（§4 + §5.2/5.3，2026-10-25）。"""

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.poi_feedback import PoiFeedbackStore

client = TestClient(create_app())
DEVICE = {"X-Device-ID": "dev-fb"}


# --- store 直测（内存态） ---------------------------------------------------


def test_store_vote_visit_review_flow():
    store = PoiFeedbackStore()
    store.vote("外滩", "上海市", up=True)
    store.vote("外滩", "上海", up=True)
    store.visit("外滩", "上海")
    store.add_review(
        "外滩", "上海", rating=5, tags=["出片", "外卡支付可用"], text="夜景绝了"
    )
    stats = store.stats_for("外滩", "上海")
    assert stats["thumbs_up"] == 2
    assert stats["visit_count"] == 1
    assert stats["review_count"] == 1
    assert stats["avg_rating"] == 5.0
    recent = store.recent_reviews("外滩", "上海")
    assert recent[0]["tags"] == ["出片", "外卡支付可用"]


def test_store_rejects_bad_rating_and_filters_tags():
    store = PoiFeedbackStore()
    import pytest

    with pytest.raises(ValueError):
        store.add_review("外滩", "上海", rating=9)
    row = store.add_review("外滩", "上海", tags=["乱写的", "人多"])
    assert row["tags"] == ["人多"]  # 词表外标签被滤


# --- API -------------------------------------------------------------------


def test_api_vote_visit_review_roundtrip():
    assert (
        client.post(
            "/api/v1/feedback/vote",
            json={"name": "洪崖洞", "city": "重庆", "up": True},
            headers=DEVICE,
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/feedback/visit",
            json={"name": "洪崖洞", "city": "重庆"},
            headers=DEVICE,
        ).status_code
        == 200
    )
    resp = client.post(
        "/api/v1/feedback/review",
        json={
            "name": "洪崖洞",
            "city": "重庆",
            "rating": 4,
            "tags": ["出片", "人多"],
            "text": "人超多但值得",
        },
        headers=DEVICE,
    )
    assert resp.status_code == 201
    body = client.get(
        "/api/v1/feedback/poi", params={"name": "洪崖洞", "city": "重庆"}
    ).json()
    assert body["stats"]["visit_count"] == 1
    assert body["stats"]["review_count"] == 1
    assert body["recent_reviews"][0]["rating"] == 4


def test_api_review_unknown_tag_422():
    resp = client.post(
        "/api/v1/feedback/review",
        json={"name": "外滩", "city": "上海", "tags": ["不存在的标签"]},
        headers=DEVICE,
    )
    assert resp.status_code == 422


def test_api_links_batch_accepts_and_rejects():
    resp = client.post(
        "/api/v1/links/batch",
        json={
            "urls": [
                "https://www.xiaohongshu.com/explore/abc123",
                "not a url at all",
                "https://www.bilibili.com/video/BV1xx411c7mD",
            ]
        },
        headers=DEVICE,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["accepted"]) == 2
    assert len(body["rejected"]) == 1
    assert body["rejected"][0]["reason"] == "invalid_url"


def test_api_links_batch_requires_device():
    resp = client.post("/api/v1/links/batch", json={"urls": ["https://a.com"]})
    assert resp.status_code == 400


# --- D2：夜聚合作业 ---------------------------------------------------------


def test_aggregate_poi_stats_merges_trip_items_and_feedback():
    from app.jobs.aggregate_poi_stats import aggregate_poi_stats
    from app.services.trip_items import TripItemService

    trip = TripItemService()
    trip.create("外滩", source="manual", city="上海")
    yu = trip.create("豫园", source="manual", city="上海")
    trip.update(yu["id"], status="scheduled", day=1)
    fb = PoiFeedbackStore()
    fb.vote("外滩", "上海", up=True)
    fb.visit("外滩", "上海")
    stats = aggregate_poi_stats(trip, fb, session_factory=None)
    assert stats["keys"] == 2
    assert stats["pg_written"] == 0  # 无 PG 也不炸
