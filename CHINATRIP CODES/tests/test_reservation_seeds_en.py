"""G1 预约名单 note_en 英文补齐守门（双语 H5，2026-10-25）。"""

from app.services.reservation_seeds import (
    FOREIGNER_TIP_EN,
    RESERVATION_V0,
    reservation_meta_for,
)


def test_every_reservation_entry_has_note_en():
    assert RESERVATION_V0, "RESERVATION_V0 不应为空"
    missing = [name for name, meta in RESERVATION_V0.items() if not meta.get("note_en")]
    assert not missing, f"缺 note_en 的条目: {missing}"


def test_note_en_is_english_not_zh_copy():
    for name, meta in RESERVATION_V0.items():
        en = meta["note_en"]
        assert isinstance(en, str) and en.strip(), name
        # 必须是英文翻译而非把中文 note 原样复制
        assert any(c.isascii() and c.isalpha() for c in en), name
        assert not any("一" <= c <= "鿿" for c in en), name


def test_note_en_keeps_numbers_and_channels():
    # 数字/时刻/渠道域必须原样保留（抽样断言）
    assert "20:00" in RESERVATION_V0["故宫"]["note_en"]
    assert "7" in RESERVATION_V0["故宫"]["note_en"]
    assert "17:00" in RESERVATION_V0["陕西历史博物馆"]["note_en"]
    assert "pgm.org.cn" in RESERVATION_V0["恭王府"]["note_en"]
    assert "mgk.org.cn" in RESERVATION_V0["敦煌莫高窟"]["note_en"]
    assert "badaling.cn" in RESERVATION_V0["八达岭长城"]["note_en"]
    assert "30" in RESERVATION_V0["敦煌莫高窟"]["note_en"]
    assert "14" in RESERVATION_V0["四川大熊猫繁育研究基地"]["note_en"]
    assert "Ctrip" in RESERVATION_V0["四川大熊猫繁育研究基地"]["note_en"]
    # 旺季秒光 → peak-season sell-out 警示保留
    assert "peak season" in RESERVATION_V0["敦煌莫高窟"]["note_en"]


def test_zh_fields_unchanged_and_present():
    for name, meta in RESERVATION_V0.items():
        assert set(("days", "release", "note", "note_en")) <= set(meta), name
        assert meta["note"], name
    # 抽样：中文口径锚点未被英文补丁改动（陕历博 2026-10-29 官网护照预约口径修正）
    assert RESERVATION_V0["故宫"]["note"] == (
        "微信小程序「故宫博物院」每日 20:00 放 7 天后门票，护照可约"
    )
    sxhm_note = RESERVATION_V0["陕西历史博物馆"]["note"]
    assert sxhm_note.endswith("外籍走官网票务系统护照预约、到馆人工窗口换票")


def test_reservation_meta_for_carries_note_en():
    meta = reservation_meta_for("故宫")
    assert meta is not None
    assert meta.get("note_en")


def test_foreigner_tip_en_exists_with_concrete_channels():
    assert FOREIGNER_TIP_EN.strip()
    for token in (
        "Trip.com",
        "Klook",
        "Forbidden City",
        "Sanxingdui",
        "Panda Base",
        "Shaanxi History Museum",
        "2nd-gen Chinese ID",
    ):
        assert token in FOREIGNER_TIP_EN, token
