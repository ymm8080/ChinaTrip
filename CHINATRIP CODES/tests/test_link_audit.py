"""外链审计（audit before input）单元测试——离线，注入假 _get。"""

import json
from pathlib import Path

import pytest

from app.services import link_audit


def _ok(status=200, final="https://x/", title="t"):
    return {
        "status": status,
        "final_url": final,
        "ok": 200 <= status < 400,
        "title": title,
    }


def _err(error="URLError"):
    return {"status": None, "ok": False, "error": error}


def _patch_get(monkeypatch, mapping):
    calls = []

    def fake(url, timeout=20):
        calls.append(url)
        return mapping.get(url, _err("no-route"))

    monkeypatch.setattr(link_audit, "_get", fake)
    return calls


@pytest.fixture(autouse=True)
def _isolate_whitelist(tmp_path, monkeypatch):
    monkeypatch.setattr(link_audit, "WHITELIST_PATH", tmp_path / "wl.json")
    return tmp_path / "wl.json"


def test_audit_ok_passes(monkeypatch):
    _patch_get(monkeypatch, {"https://ok.example/": _ok()})
    entry = link_audit.audit("https://ok.example/")
    assert entry["verdict"] == "ok"
    assert link_audit.usable(entry["verdict"])


def test_audit_bare_domain_gets_https(monkeypatch):
    _patch_get(monkeypatch, {"https://ok.example/": _ok()})
    entry = link_audit.audit("ok.example/")
    assert entry["url"] == "https://ok.example/"
    assert entry["verdict"] == "ok"


def test_audit_blocked_bot_is_usable(monkeypatch):
    _patch_get(monkeypatch, {"https://bot.example/x": _ok(status=403)})
    entry = link_audit.audit("https://bot.example/x")
    assert entry["verdict"] == "blocked_bot"
    assert link_audit.usable(entry["verdict"])


def test_audit_http_only_display_url(monkeypatch):
    _patch_get(
        monkeypatch,
        {
            "https://nossl.example/": _err("SSL WRONG_VERSION_NUMBER"),
            "http://nossl.example/": _ok(),
        },
    )
    url, entry = link_audit.audit_or_none("https://nossl.example/")
    assert entry["verdict"] == "ok_http_only"
    assert url == "http://nossl.example/"


def test_audit_dead_returns_none(monkeypatch):
    _patch_get(
        monkeypatch,
        {
            "https://dead.example/": _err("SSL"),
            "http://dead.example/": _err("404"),
        },
    )
    url, entry = link_audit.audit_or_none("https://dead.example/")
    assert url is None
    assert entry["verdict"] == "dead"
    assert not link_audit.usable(entry["verdict"])


def test_audit_or_none_empty_input():
    url, entry = link_audit.audit_or_none(None)
    assert url is None and entry is None


def test_row_fields_clean_dead_and_record(monkeypatch, _isolate_whitelist):
    _patch_get(
        monkeypatch,
        {
            "https://dead.example/": _err("SSL"),
            "http://dead.example/": _err("404"),
            "https://ok.example/": _ok(),
        },
    )
    row = {
        "ticket_url": "dead.example/",
        "official_url": "https://ok.example/",
        "source_url": "",
    }
    dead = link_audit.audit_row_fields(
        row, ("ticket_url", "official_url", "source_url")
    )
    assert row["ticket_url"] is None
    assert row["official_url"] == "https://ok.example/"
    assert len(dead) == 1 and "ticket_url" in dead[0]
    wl = json.loads(_isolate_whitelist.read_text(encoding="utf-8"))
    assert wl["links"]["https://ok.example/"]["verdict"] == "ok"
    assert wl["links"]["https://dead.example/"]["verdict"] == "dead"


def test_recorded_link_becomes_displayable(tmp_path, monkeypatch):
    from app.services.itinerary import legs

    _patch_get(monkeypatch, {"https://ok.example/": _ok()})
    url, _entry = link_audit.audit_or_none("https://ok.example/")
    assert url == "https://ok.example/"
    monkeypatch.setattr(legs, "_VERIFIED_LINKS_FILE", link_audit.WHITELIST_PATH)
    monkeypatch.setattr(legs, "_LINK_CACHE", {"mtime": None, "links": {}})
    assert legs._url("ok.example/") == "https://ok.example/"


def test_seed_urls_are_audited():
    """种子文件里的每条 URL 必须已在白名单且非 dead（audit before input 的静态门）。"""
    root = Path(__file__).resolve().parents[1]
    seed = json.loads(
        (root / "DESIGN" / "data" / "access_services_seed_2026-11.json").read_text(
            encoding="utf-8"
        )
    )
    links = json.loads(
        (root / "app" / "data" / "verified_links.json").read_text(encoding="utf-8")
    )["links"]
    missing: list[str] = []
    for service in seed.get("services") or []:
        for field in ("ticket_url", "official_url", "source_url"):
            raw = service.get(field)
            if not raw:
                continue
            url = link_audit.normalize(raw)
            entry = links.get(url)
            if entry is None:
                alt = (
                    "http://" + url[len("https://") :]
                    if url.startswith("https://")
                    else "https://" + url[len("http://") :]
                )
                entry = links.get(alt)
            if entry is None or str(entry.get("verdict")) in ("dead", "unknown", ""):
                missing.append(f"{service.get('service_name')}:{field}:{raw}")
    assert not missing, missing


def test_refresh_reservation_rules_rejects_dead_source(monkeypatch):
    from app.jobs import refresh_reservation_rules as mod

    _patch_get(
        monkeypatch,
        {
            "https://dead.example/": _err("SSL"),
            "http://dead.example/": _err("404"),
        },
    )
    rule = {"advance_days": 7, "channel": "官网", "source": "https://dead.example/"}
    assert mod._audit_source(rule) is None
