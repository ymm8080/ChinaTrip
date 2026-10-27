"""预约自动化三档栈测试（L1/L2/L3 + 档位选择与降级链）。"""

from fastapi.testclient import TestClient

from app.main import create_app
from app.services import booking_auto as ba

client = TestClient(create_app())
DEVICE = {"X-Device-ID": "dev-ba"}


# --- 档位解析与降级 ---------------------------------------------------------


def test_tier_l1_always_available():
    tier, note = ba.resolve_tier("L1")
    assert tier == ba.BookingTier.L1 and note is None


def test_tier_l2_degrades_without_keys(monkeypatch):
    class _S:
        ctrip_union_api_key = ""
        tongcheng_api_key = ""
        meituan_api_key = ""
        klook_api_key = ""
        tripcom_api_key = ""
        alliance_id = ""
        alliance_sid = ""

    monkeypatch.setattr(ba, "get_settings", lambda: _S())
    tier, note = ba.resolve_tier("L2")
    assert tier == ba.BookingTier.L1 and "降级" in note


def test_tier_l2_kept_with_klook_key(monkeypatch):
    class _S:
        ctrip_union_api_key = "ct"  # 国内主力键即可点亮 L2
        tongcheng_api_key = ""
        meituan_api_key = ""
        klook_api_key = ""
        tripcom_api_key = ""
        alliance_id = ""
        alliance_sid = ""

    monkeypatch.setattr(ba, "get_settings", lambda: _S())
    tier, note = ba.resolve_tier("L2")
    assert tier == ba.BookingTier.L2 and note is None


def test_tier_l3_is_manual_confirm_with_note():
    # 无 key 时 L3 请求 → 降 L1；有 key 时 L3 = manual_confirm 形态
    tier, note = ba.resolve_tier("L3")
    assert tier in (ba.BookingTier.L1, ba.BookingTier.L3)
    assert note is not None


def test_available_tiers_catalog_shape():
    tiers = ba.available_tiers()
    assert [t["tier"] for t in tiers] == ["L1", "L2", "L3"]
    assert tiers[0]["available"] is True  # L1 恒可用


# --- L1 放票任务 ------------------------------------------------------------


def test_build_reservation_tasks_date_math():
    tasks = ba.build_reservation_tasks(
        [
            {"name": "故宫博物院", "city": "北京", "day": 3},
            {"name": "外滩", "city": "上海", "day": 1},  # 不在名单，忽略
        ],
        start_date="2026-11-10",
    )
    assert len(tasks) == 1
    t = tasks[0]
    assert t.visit_date == "2026-11-12"  # 第 3 天
    assert t.open_date == "2026-11-05"  # 提前 7 天开抢
    assert t.release_time == "20:00"


def test_build_reservation_tasks_without_start_date():
    tasks = ba.build_reservation_tasks(
        [{"name": "三星堆博物馆", "day": 1}], start_date=None
    )  # noqa: E501
    assert tasks and tasks[0].open_date is None  # 任务仍在，日期待补


# --- 直达链接 / 下单意图 -----------------------------------------------------


def test_booking_link_appends_alliance_only_when_set(monkeypatch):
    class _S:
        ctrip_union_api_key = ""
        tongcheng_api_key = ""
        meituan_api_key = ""
        klook_api_key = ""
        tripcom_api_key = ""
        alliance_id = ""
        alliance_sid = ""
        booking_search_template = (
            "https://www.trip.com/attractions/search?keyword={keyword}"
        )

    monkeypatch.setattr(ba, "get_settings", lambda: _S())
    plain = ba.booking_link_for("故宫", "北京")
    assert "allianceid" not in plain and "keyword=" in plain

    _S.alliance_id, _S.alliance_sid = "A1", "S1"
    linked = ba.booking_link_for("故宫", "北京")
    assert "allianceid=A1" in linked and "sid=S1" in linked


def test_order_intent_uses_poi_url_first_and_never_autopays():
    intent = ba.build_order_intent(
        "故宫", "北京", booking_url="https://mp.weixin.qq.com/poi/123"
    )
    assert intent.authorization_url == "https://mp.weixin.qq.com/poi/123"
    assert intent.requires_user_confirmation is True  # 铁律 22：支付归用户
    assert intent.channel == "manual_confirm"


# --- L2 unknown ------------------------------------------------------------


def test_check_availability_splits_by_venue_type():
    """L2 语义纠偏（2026-10-25）：预约名单馆=官方配额不可查；商业 SKU
    无 provider 时=unknown 诚实缺省；两者都不编造库存。"""
    import asyncio

    # 预约制馆：即使 provider 可用也返回 official_quota（联盟 API 不覆盖官方配额）
    quota = asyncio.run(ba.check_availability("故宫博物院", "北京", "2026-11-12"))
    assert quota.value == "official_quota"
    # 商业 SKU：无联盟 key → unknown
    status = asyncio.run(ba.check_availability("欢乐谷", "北京", "2026-11-12"))
    assert status.value == "unknown"


# --- API --------------------------------------------------------------------


def test_api_tiers_tasks_intent_select():
    assert client.get("/api/v1/booking-auto/tiers").json()["tiers"][0]["tier"] == "L1"
    body = client.post(
        "/api/v1/booking-auto/tasks",
        json={
            "visits": [{"name": "故宫", "city": "北京", "day": 2}],
            "start_date": "2026-11-10",
        },
    ).json()
    assert body["tasks"][0]["open_date"] == "2026-11-04"
    intent = client.post(
        "/api/v1/booking-auto/order-intent",
        json={"name": "故宫", "city": "北京", "tier": "L3"},
    ).json()
    assert intent["requires_user_confirmation"] is True
    # 伪闭环（2026-10-25）：发起即落 action_handoffs 留痕，回填管道可接
    assert intent["handoff_id"]
    from app.api.backfill import get_handoff_store

    rec = get_handoff_store().get(intent["handoff_id"])
    assert rec is not None and rec.status == "opened"
    assert rec.action_type == "site_ticket"
    assert rec.url == intent["authorization_url"]
    chk = client.post(
        "/api/v1/booking-auto/check",
        json={"name": "故宫", "city": "北京", "visit_date": "2026-11-11"},
    ).json()
    assert chk["availability"] in (
        "unknown",
        "ok",
        "low",
        "sold_out",
        "official_quota",
    )
    assert (
        client.post(
            "/api/v1/booking-auto/select",
            json={"tier": "L2"},
            headers=DEVICE,
        ).status_code
        == 200
    )
    assert (
        client.get("/api/v1/booking-auto/selected", headers=DEVICE).json()["tier"]
        == "L2"
    )  # noqa: E501


# --- geo 分流（境外→Trip.com / 国内→美团，2026-10-25 用户拍板） --------------


def test_geo_split_mainland_vs_overseas():
    from app.services.geo_split import (
        booking_channel_for_ip,
        booking_search_url,
        client_ip,
        is_mainland_ip,
    )

    # 真实 CN 公网段（1.0.1.0/24 属 APNIC CN 委派）
    assert is_mainland_ip("1.0.1.5") is True
    assert booking_channel_for_ip("1.0.1.5") == "meituan"
    # 海外公网（8.8.8.8 = US）
    assert is_mainland_ip("8.8.8.8") is False
    assert booking_channel_for_ip("8.8.8.8") == "tripcom"
    # 私网/回环/None → 境外侧默认（安全侧：主要客户是外国人）
    for ip in ("127.0.0.1", "192.168.1.5", None, "not-an-ip"):
        assert booking_channel_for_ip(ip) == "tripcom", ip
    # XFF 首段优先
    assert client_ip("8.8.8.8, 10.0.0.1", "1.0.1.5") == "8.8.8.8"
    assert client_ip(None, "1.0.1.5") == "1.0.1.5"
    # URL 分流：两渠道模板都带 keyword + 联盟参数纪律
    url_cn = booking_search_url("meituan", "故宫", "北京")
    assert "meituan.com" in url_cn and "%E5%8C%97%E4%BA%AC" in url_cn
    url_overseas = booking_search_url("tripcom", "故宫", "北京")
    assert "trip.com" in url_overseas


def test_order_intent_geo_routes_by_request_ip():
    # 模拟境外客户端（XFF 海外 IP）→ trip.com
    r1 = client.post(
        "/api/v1/booking-auto/order-intent",
        json={"name": "故宫", "city": "北京", "tier": "L3"},
        headers={**DEVICE, "X-Forwarded-For": "8.8.8.8"},
    ).json()
    assert r1["geo_channel"] == "tripcom"
    assert "trip.com" in r1["authorization_url"]
    # 模拟国内客户端（XFF CN IP）→ 美团
    r2 = client.post(
        "/api/v1/booking-auto/order-intent",
        json={"name": "故宫", "city": "北京", "tier": "L3"},
        headers={**DEVICE, "X-Forwarded-For": "1.0.1.5"},
    ).json()
    assert r2["geo_channel"] == "meituan"
    assert "meituan.com" in r2["authorization_url"]
    # 显式 booking_url 优先（poi.booking_url 库列），geo 只补缺省
    r3 = client.post(
        "/api/v1/booking-auto/order-intent",
        json={
            "name": "故宫",
            "city": "北京",
            "booking_url": "https://mp.weixin.qq.com/x",
        },
        headers={**DEVICE, "X-Forwarded-For": "1.0.1.5"},
    ).json()
    assert r3["authorization_url"] == "https://mp.weixin.qq.com/x"


# --- 🎭 演出目录（GET /shows：04 CSV 底库 → 预订页分区数据源） ------------------

from types import SimpleNamespace  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from app.api.booking_auto import get_show_session_factory  # noqa: E402
from app.api.booking_auto import router as booking_auto_router  # noqa: E402


class _ShowQuery:
    def __init__(self, rows):
        self._rows = rows

    def options(self, *a, **k):
        return self

    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def all(self):
        return list(self._rows)


class _ShowSession:
    def __init__(self, rows, exc=None):
        self._rows = rows
        self._exc = exc
        self.calls = 0

    def query(self, *a, **k):
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        return _ShowQuery(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _show_row(**over):
    base = dict(
        name_zh="长恨歌",
        name_en=None,
        city="西安市",
        booking_url="https://m.ctrip.com/webapp/cw/sku/x",
        intro="每年冬季例行停演，行前请确认档期",
        intro_en=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _shows_app(session) -> TestClient:
    app = FastAPI()
    app.dependency_overrides[get_show_session_factory] = lambda: lambda: session
    app.include_router(booking_auto_router)
    return TestClient(app)


def test_shows_catalog_flags_direct_and_passes_note():
    rows = [
        _show_row(),
        _show_row(
            name_zh="西安千古情",
            booking_url=None,
            intro=None,
            intro_en="Nightly immersive show",
        ),
        _show_row(name_zh="秦俑情", booking_url=None, intro=None, intro_en=None),
    ]
    resp = _shows_app(_ShowSession(rows)).get(
        "/api/v1/booking-auto/shows", params={"city": "西安"}
    )
    assert resp.status_code == 200
    shows = resp.json()["shows"]
    assert len(shows) == 3
    assert shows[0]["name"] == "长恨歌" and shows[0]["has_direct"] is True
    assert all(s["has_direct"] is False for s in shows[1:])
    assert shows[0]["note"] == "每年冬季例行停演，行前请确认档期"
    assert shows[1]["note"] == "Nightly immersive show"  # intro 空回退 intro_en
    assert shows[2]["note"] is None


def test_shows_empty_city_still_200():
    resp = _shows_app(_ShowSession([])).get(
        "/api/v1/booking-auto/shows", params={"city": "廊坊"}
    )
    assert resp.status_code == 200
    assert resp.json()["shows"] == []


def test_shows_db_down_returns_503():
    session = _ShowSession([], exc=OperationalError("stmt", {}, Exception("conn")))
    resp = _shows_app(session).get(
        "/api/v1/booking-auto/shows", params={"city": "西安"}
    )
    assert resp.status_code == 503
