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
