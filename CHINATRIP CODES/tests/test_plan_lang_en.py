"""P3 plan-agent bilingual: reply/hint strings follow the lang contextvar.

zh stays byte-identical by default; set_lang("en") switches the same call
to EN. Autouse fixture resets to zh (contextvar leaks across tests).
"""

import pytest

from app.services.agent.plan import _reservation_hint, _unspecified
from app.services.lang_ctx import set_lang


@pytest.fixture(autouse=True)
def _reset_lang():
    yield
    set_lang("zh")


def test_unspecified_city_placeholder_follows_lang():
    assert _unspecified() == "未标注"
    set_lang("en")
    assert _unspecified() == "Unspecified"


def test_reservation_hint_library_column_zh_default():
    hint = _reservation_hint("某景点", {"reservation_advance_days": 7})
    assert hint is not None
    assert hint == "需提前 7 天预约（建议 Trip.com/Klook 代抢）"


def test_reservation_hint_library_column_en():
    set_lang("en")
    hint = _reservation_hint("Some sight", {"reservation_advance_days": 7})
    assert hint == "Book 7 days ahead (Trip.com/Klook can secure it for you)"
    bare = _reservation_hint("Some sight", {"reservation_required": True})
    assert bare == "Reservation required (Trip.com/Klook can secure it for you)"


def test_reservation_hint_seed_fallback_en_uses_note_en_and_tip_en():
    set_lang("en")
    # "故宫" is the first seed whose key is a substring of the full site name
    hint = _reservation_hint("故宫博物院", {})
    assert hint is not None
    assert hint.startswith("Book 7 days ahead (")
    assert "passports accepted for booking" in hint
    assert "standard workaround" in hint  # FOREIGNER_TIP_EN
    assert "微信小程序" not in hint


def test_reservation_hint_seed_fallback_zh_unchanged():
    hint = _reservation_hint("故宫博物院", {})
    assert hint is not None
    assert hint.startswith("需提前 7 天预约（")
    assert "护照可约" in hint
    assert "代抢" in hint  # FOREIGNER_TIP


def test_reservation_hint_csv_no_reservation_zh():
    """09 表全量判词兜底：大足石刻=实名购票制无需预约（2026-10-29 已核），
    渠道+外籍护照购票口径都上卡。"""
    hint = _reservation_hint("大足石刻", {})
    assert hint is not None
    assert hint.startswith("无需预约（「大足石刻」公众号")
    assert "外籍：同国内购票制" in hint  # 现场窗口凭护照购票


def test_reservation_hint_csv_no_reservation_en():
    set_lang("en")
    hint = _reservation_hint("大足石刻", {})
    assert hint is not None
    assert hint.startswith("No reservation needed (「大足石刻」公众号")
    assert "foreigners: 同国内购票制" in hint


def test_reservation_hint_csv_required_row():
    """良渚古城：09 表需预约行（提前 1-7 天）不在名单 v0——走 CSV 兜底。"""
    hint = _reservation_hint("良渚古城遗址", {})
    assert hint is not None
    assert hint.startswith("需提前 7 天预约")
    assert "「良渚古城」微信公众号" in hint
    assert "护照线上预约难" in hint  # 外籍口径


def test_reservation_hint_unknown_site_none():
    """库列/名单/09 表全不命中 → None（前端兜底「预约信息无」）。"""
    assert _reservation_hint("某某无名景点", {}) is None
