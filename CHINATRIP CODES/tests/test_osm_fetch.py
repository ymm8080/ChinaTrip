"""app.jobs.osm_fetch 纯逻辑单测（不发网络请求）."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import app.jobs.osm_fetch as mod
from app.jobs.osm_fetch import last_serial, pending_serials, serial_path

_EPOCH = datetime(2012, 9, 12, 8, 15, 45, tzinfo=timezone.utc)


# ---------- serial_path：序号 -> 三段相对路径 ----------


def test_serial_path_zero_padded() -> None:
    assert serial_path(123717) == "000/123/717"
    assert serial_path(1) == "000/000/001"


# ---------- last_serial：共用水位文件解析 ----------


def test_last_serial_reads_planet_name(tmp_path: Path) -> None:
    state = tmp_path / "osm_state.json"
    state.write_text('{"last_osc": "planet_hour_000123717.osc.gz"}', encoding="utf-8")
    assert last_serial(state) == 123717


def test_last_serial_none_for_missing_or_foreign_state(tmp_path: Path) -> None:
    assert last_serial(tmp_path / "absent.json") is None
    state = tmp_path / "s.json"
    state.write_text('{"last_osc": "china-250930.osc.gz"}', encoding="utf-8")
    assert last_serial(state) is None  # 旧 Geofabrik 命名不识别


# ---------- pending_serials：水位推进与追补上限 ----------


def test_pending_serials_after_watermark() -> None:
    assert pending_serials(123717, 123719) == [123718, 123719]


def test_pending_serials_none_takes_latest_only() -> None:
    assert pending_serials(None, 123719) == [123719]


def test_pending_serials_capped_catchup() -> None:
    # 停跑 100 小时只追补最近 MAX_CATCHUP 个
    latest = 123717
    got = pending_serials(latest - 100, latest)
    assert got == list(range(latest - mod.MAX_CATCHUP + 1, latest + 1))


def test_pending_serials_empty_when_caught_up() -> None:
    assert pending_serials(123719, 123719) == []


# ---------- probe_latest_serial：探测逻辑（注入假网络） ----------


def test_probe_latest_serial_walks_through_gap(monkeypatch) -> None:
    # 猜 101（+1 过冲探测失败），向下回退到 99 -> 最新是 99（时钟偏快兜底）
    monkeypatch.setattr(mod, "fetch_serial_state", lambda s: s <= 99)
    assert mod.probe_latest_serial(_EPOCH + timedelta(hours=100)) == 99


def test_probe_latest_serial_none_when_nothing_exists(monkeypatch) -> None:
    monkeypatch.setattr(mod, "fetch_serial_state", lambda s: False)
    assert mod.probe_latest_serial(_EPOCH + timedelta(hours=100)) is None


def test_probe_latest_serial_walks_up_past_hole(monkeypatch) -> None:
    # 猜 101，102/103 存在 -> 上探到 103
    monkeypatch.setattr(mod, "fetch_serial_state", lambda s: s <= 103)
    assert mod.probe_latest_serial(_EPOCH + timedelta(hours=100)) == 103
