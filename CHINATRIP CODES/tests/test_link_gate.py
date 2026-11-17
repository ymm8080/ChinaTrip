"""规划页外链白名单闸（2026-11-16 用户拍板「链接必须先验证」）。

用户实报「you do not verify the booking link you post on planning page」：
八达岭卡「购票/预约」指向 ticket.badaling.cn（TLS 握手失败 + http 404 死链）。
现在 legs._url 只放行 app/data/verified_links.json 里实检通过的链接。
"""

import json

from app.services.itinerary import legs


def _gate(tmp_path, monkeypatch, links: dict):
    path = tmp_path / "verified_links.json"
    path.write_text(json.dumps({"links": links}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(legs, "_VERIFIED_LINKS_FILE", path)
    monkeypatch.setattr(legs, "_LINK_CACHE", {"mtime": None, "links": {}})
    return path


def test_verified_link_passes_and_bare_domain_gets_https(tmp_path, monkeypatch):
    _gate(tmp_path, monkeypatch, {"https://www.badaling.cn": {"verdict": "ok"}})
    assert legs._url("www.badaling.cn") == "https://www.badaling.cn"
    assert legs._url("https://www.badaling.cn") == "https://www.badaling.cn"


def test_dead_link_is_never_rendered(tmp_path, monkeypatch):
    _gate(
        tmp_path,
        monkeypatch,
        {"https://ticket.badaling.cn": {"verdict": "dead", "status": None}},
    )
    assert legs._url("ticket.badaling.cn") == ""
    assert legs._url("https://ticket.badaling.cn") == ""


def test_unlisted_link_is_never_rendered(tmp_path, monkeypatch):
    _gate(tmp_path, monkeypatch, {})
    assert legs._url("https://example.com/booking") == ""


def test_http_only_uses_http_display_url(tmp_path, monkeypatch):
    _gate(
        tmp_path,
        monkeypatch,
        {
            "https://www.hbww.org": {
                "verdict": "ok_http_only",
                "display_url": "http://www.hbww.org",
            }
        },
    )
    assert legs._url("www.hbww.org") == "http://www.hbww.org"


def test_blocked_bot_and_retry_pass(tmp_path, monkeypatch):
    _gate(
        tmp_path,
        monkeypatch,
        {
            "https://gs.ctrip.com/x": {"verdict": "blocked_bot"},
            "https://www.798artdistrict.com.cn": {"verdict": "ok_retry"},
        },
    )
    assert legs._url("https://gs.ctrip.com/x") == "https://gs.ctrip.com/x"
    assert legs._url("https://www.798artdistrict.com.cn") == (
        "https://www.798artdistrict.com.cn"
    )


def test_missing_whitelist_file_drops_everything(tmp_path, monkeypatch):
    monkeypatch.setattr(legs, "_VERIFIED_LINKS_FILE", tmp_path / "nope.json")
    monkeypatch.setattr(legs, "_LINK_CACHE", {"mtime": None, "links": {}})
    assert legs._url("https://www.badaling.cn") == ""


def test_corrupt_whitelist_drops_everything(tmp_path, monkeypatch):
    path = tmp_path / "verified_links.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(legs, "_VERIFIED_LINKS_FILE", path)
    monkeypatch.setattr(legs, "_LINK_CACHE", {"mtime": None, "links": {}})
    assert legs._url("https://www.badaling.cn") == ""


def test_card_booking_url_gated_on_annotate(tmp_path, monkeypatch):
    """卡面 🎫 预约按钮的 booking_url 同样过闸：死链清空，活链补全 scheme。"""
    from datetime import time

    from app.services.itinerary.legs import annotate_legs
    from app.services.itinerary.models import (
        DayPlan,
        GeoPoint,
        ItineraryPlan,
        VisitItem,
    )

    _gate(tmp_path, monkeypatch, {"https://www.badaling.cn": {"verdict": "ok"}})
    base = dict(
        city="北京", day=1, duration_minutes=60, category="sight",
        location=GeoPoint(lon=116.41, lat=39.91),
        start_time=time(9, 0), end_time=time(10, 0),
    )
    dead = VisitItem(
        item_id="d", name="景山公园", booking_url="https://bjgyol.com.cn", **base
    )
    alive = VisitItem(
        item_id="a", name="八达岭长城", booking_url="www.badaling.cn", **base
    )
    plan = ItineraryPlan(
        itinerary_id="x", cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=[dead, alive])],
        assumptions=[],
    )
    annotate_legs(plan)
    assert dead.booking_url is None
    assert alive.booking_url == "https://www.badaling.cn"
