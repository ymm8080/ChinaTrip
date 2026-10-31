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
        reservation_required=None,
        reservation_advance_days=None,
        booking_url=None,
        ticket_price_min=None,
        ticket_price_max=None,
        ticket_source=None,
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
        "reservation_required",
        "reservation_advance_days",
        "reservation_release_time",
        "reservation_note",
        "reservation_note_en",
        "foreigner_tip",
        "foreigner_tip_en",
        "booking_url",
        "ticket_price_min",
        "ticket_price_max",
        "ticket_source",
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


# --- 预约/订票出参 (2026-10-29)：库列优先，RESERVATION_V0 兜底 -------------------


def test_non_reservation_site_booking_fields_all_null():
    """非预约制景点（洪崖洞不在名单、库列空）→ 预约组全 null，不出提示。"""
    session = FakeSession([[make_row()]])
    resp = make_app(session).get(
        "/api/pois/detail", params={"city": "重庆", "name": "洪崖洞"}
    )
    body = resp.json()
    assert body["reservation_required"] is None
    assert body["reservation_advance_days"] is None
    assert body["reservation_release_time"] is None
    assert body["reservation_note"] is None
    assert body["foreigner_tip"] is None
    assert body["booking_url"] is None


def test_reservation_fields_from_seeds_fallback():
    """库列全空的名单馆（故宫博物院）→ 名单兜底：天数/放票时刻/双语提示。"""
    session = FakeSession(
        [[make_row(name_zh="故宫博物院", source="5a", tags=None)], []]
    )
    resp = make_app(session).get(
        "/api/pois/detail", params={"city": "北京", "name": "故宫博物院"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["reservation_required"] is True
    assert body["reservation_advance_days"] == 7
    assert body["reservation_release_time"] == "20:00"
    assert "小程序" in body["reservation_note"]
    assert "passport" in body["reservation_note_en"]
    assert body["foreigner_tip"]
    assert body["foreigner_tip_en"]
    assert body["booking_url"] is None  # 名单无 URL；H5 走 order-intent geo 分流
    assert "5a" in body["tags"]  # 名单行 tags 空 → tier 接线照常注入


def test_reservation_db_columns_win_over_seeds():
    """库列有值（refresh_reservation_rules 回写）→ 天数/URL 以库列为准
    （名单同馆 10 天不改写 12 天库列值），名单提示不再覆盖
    （plan._reservation_hint 同语义）；release 无库列恒由名单补时刻。"""
    session = FakeSession(
        [
            [
                make_row(
                    name_zh="恭王府博物馆",
                    reservation_required=True,
                    reservation_advance_days=12,
                    booking_url="https://pgm.org.cn",
                )
            ]
        ]
    )
    resp = make_app(session).get(
        "/api/pois/detail", params={"city": "北京", "name": "恭王府博物馆"}
    )
    body = resp.json()
    assert body["reservation_required"] is True
    assert body["reservation_advance_days"] == 12
    assert body["booking_url"] == "https://pgm.org.cn"
    assert body["reservation_note"] is None
    assert body["reservation_release_time"] == "20:00"  # 名单「恭王府」release 补时刻
    assert body["foreigner_tip"]


def test_reservation_seed_name_containment_match():
    """互含容错：库存「敦煌莫高窟景区」⊂ 名单键「敦煌莫高窟」（_same_site 同款）。"""
    session = FakeSession([[make_row(name_zh="敦煌莫高窟景区")]])
    resp = make_app(session).get(
        "/api/pois/detail", params={"city": "敦煌", "name": "敦煌莫高窟景区"}
    )
    body = resp.json()
    assert body["reservation_required"] is True
    assert body["reservation_advance_days"] == 30
    assert body["reservation_release_time"] is None  # 名单 "00:00"=未注明 → 出参 None


def test_ticket_price_passthrough():
    """ctrip 刷新链回填的票价列 → 出参 int 原样（此前无任何 API 暴露票价）。"""
    session = FakeSession(
        [[make_row(ticket_price_min=40, ticket_price_max=60, ticket_source="ctrip")]]
    )
    resp = make_app(session).get(
        "/api/pois/detail", params={"city": "重庆", "name": "洪崖洞"}
    )
    body = resp.json()
    assert body["ticket_price_min"] == 40
    assert body["ticket_price_max"] == 60
    assert body["ticket_source"] == "ctrip"
