"""Tests for GET /api/pois/detail (v2.5 POI 底库新字段).

App assembly mirrors tests/test_itineraries_api.py: fresh app +
dependency_overrides, no real DB. The fake session queues one result set
per session.query() call — [exact-stage rows] then [fuzzy-stage rows] —
so both lookup stages are exercised deterministically.
"""

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.api.pois import get_poi_session_factory
from app.api.pois import router as pois_router

PHOTOS = [
    {
        "url": "https://img.example/hongyadong.jpg",
        "source": "wikidata",
        "license": "CC-BY-SA",
    },
    {
        "url": "https://img.example/hongyadong-2.jpg",
        "source": "wikidata",
        "license": "CC-BY-SA",
    },
]


def make_row(**over) -> SimpleNamespace:
    base = dict(
        id="11111111-1111-1111-1111-111111111111",
        source="amap",
        origin="osm",
        city="重庆市",
        name_zh="洪崖洞",
        name_en="Hongya Cave",
        category="sight",
        status="active",
        address="嘉陵江滨江路",
        opening_hours="09:00-23:00",
        hours_source="amap",
        phone="023-63039999",
        website="https://example.com",
        rating=4.6,
        rating_source="amap",
        tags=["michelin_1star", "black_pearl_1diamond"],
        tags_source="manual",
        intro="吊脚楼建筑群",
        intro_source="wikidata",
        photos=PHOTOS,
        photos_source="wikidata",
        best_visit_time="night",
        best_visit_time_source="manual",
        suggested_duration_min=90,
    )
    base.update(over)
    return SimpleNamespace(**base)


class FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def options(self, *a, **k):
        return self

    def filter(self, *a, **k):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class FakeSession:
    def __init__(self, queued, exc=None):
        self._queued = list(queued)
        self._exc = exc
        self.calls = 0

    def query(self, *a, **k):
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        return FakeQuery(self._queued.pop(0) if self._queued else [])

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def make_app(session) -> TestClient:
    app = FastAPI()
    app.dependency_overrides[get_poi_session_factory] = lambda: lambda: session
    app.include_router(pois_router)
    return TestClient(app)


# --- exact hit -----------------------------------------------------------------


def test_exact_hit_returns_200_with_new_fields():
    session = FakeSession([[make_row()]])
    resp = make_app(session).get(
        "/api/pois/detail", params={"city": "重庆", "name": "洪崖洞"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["poi_id"] == "11111111-1111-1111-1111-111111111111"
    assert body["source"] == "amap"
    for field in (
        "origin",
        "phone",
        "website",
        "rating",
        "rating_source",
        "tags",
        "tags_source",
        "intro",
        "intro_source",
        "photos",
        "photos_source",
        "best_visit_time",
        "best_visit_time_source",
        "suggested_duration_min",
    ):
        assert field in body
    assert body["rating"] == 4.6  # Decimal coerced to float
    assert body["tags"] == ["michelin_1star", "black_pearl_1diamond"]  # tier 0 不加标签
    assert body["best_visit_time"] == "night"
    assert body["suggested_duration_min"] == 90
    # exact hit: fuzzy stage never queried; 读侧 tier 接线后多一次名单查询
    assert session.calls == 2


# --- fuzzy hit -----------------------------------------------------------------


def test_fuzzy_hit_parenthesized_and_spaced_variant():
    row = make_row(name_zh="洪崖洞民俗风貌区")
    session = FakeSession([[], [row]])
    resp = make_app(session).get(
        "/api/pois/detail",
        params={"city": "重庆市", "name": "洪崖洞（民俗风貌区） "},
    )
    assert resp.status_code == 200
    assert resp.json()["name_zh"] == "洪崖洞民俗风貌区"
    assert session.calls == 3  # exact missed → fuzzy fetched → tier 名单查询


# --- miss / db down -------------------------------------------------------------


def test_miss_returns_404():
    session = FakeSession([[], []])
    resp = make_app(session).get(
        "/api/pois/detail", params={"city": "重庆", "name": "不存在的景点"}
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "poi not found"}


def test_db_unreachable_returns_503():
    session = FakeSession([], exc=OperationalError("stmt", {}, Exception("conn")))
    resp = make_app(session).get(
        "/api/pois/detail", params={"city": "重庆", "name": "洪崖洞"}
    )
    assert resp.status_code == 503


# --- photos passthrough ---------------------------------------------------------


def test_photos_jsonb_structure_passes_through_unchanged():
    session = FakeSession([[make_row()]])
    resp = make_app(session).get(
        "/api/pois/detail", params={"city": "重庆", "name": "洪崖洞"}
    )
    assert resp.status_code == 200
    assert resp.json()["photos"] == PHOTOS


# --- 读侧 tier 接线 (2026-10-28)：5A/unesco 名单行 tags 列 0 覆盖，出参前判级 ---


def test_tier_tag_injected_for_skeleton_5a_row():
    """source='5a' 骨架行（tags 空）→ 出参 tags 注入 '5a'，H5 徽章可见。"""
    session = FakeSession([[make_row(source="5a", tags=None)], []])
    resp = make_app(session).get(
        "/api/pois/detail", params={"city": "重庆", "name": "洪崖洞"}
    )
    assert resp.status_code == 200
    assert resp.json()["tags"] == ["5a"]


def test_tier_tag_injected_via_heritage_overlap():
    """裸 amap 行名 ⊂ 名单行名 → 按互含判级注入（灵隐飞来峰 ⊂ 灵隐飞来峰景区）。"""
    row = make_row(name_zh="灵隐飞来峰", tags=[])
    session = FakeSession([[row], [("灵隐飞来峰景区", "5a")]])
    resp = make_app(session).get(
        "/api/pois/detail", params={"city": "杭州", "name": "灵隐飞来峰"}
    )
    assert resp.status_code == 200
    assert "5a" in resp.json()["tags"]


def test_already_tier_tagged_row_skips_heritage_query():
    """行内已有层级标签：不再查名单（出参原样，少一次查询）。"""
    session = FakeSession([[make_row(tags=["unesco"])]])
    resp = make_app(session).get(
        "/api/pois/detail", params={"city": "重庆", "name": "洪崖洞"}
    )
    assert resp.status_code == 200
    assert resp.json()["tags"] == ["unesco"]
    assert session.calls == 1
