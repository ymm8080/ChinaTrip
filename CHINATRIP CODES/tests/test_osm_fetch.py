"""osm_fetch 下载器：链接解析 / 水位推进 / 续传复用."""

from pathlib import Path

from app.jobs.osm_fetch import (
    fetch_pending,
    last_applied,
    list_osc_hrefs,
    pending_hrefs,
)

_HTML = (
    '<html><a href="000/002/001.osc.gz">1</a>'
    '<A HREF="000/002/002.osc.gz">2</A>'
    '<a href="000/002/001.osc.gz.md5">md5</a></html>'
)


def test_list_osc_hrefs_filters_and_sorts() -> None:
    assert list_osc_hrefs(_HTML) == ["000/002/001.osc.gz", "000/002/002.osc.gz"]


def test_pending_hrefs_watermark() -> None:
    hrefs = ["000/002/001.osc.gz", "000/002/002.osc.gz"]
    assert pending_hrefs(hrefs, None) == ["000/002/002.osc.gz"]
    assert pending_hrefs(hrefs, "001.osc.gz") == ["000/002/002.osc.gz"]
    assert pending_hrefs(hrefs, "002.osc.gz") == []
    # 水位滑出保留窗口：只追最新
    assert pending_hrefs(hrefs, "000/001/999.osc.gz") == ["000/002/002.osc.gz"]


def test_last_applied_missing_or_broken(tmp_path: Path) -> None:
    assert last_applied(tmp_path / "absent.json") is None
    state = tmp_path / "state.json"
    state.write_text("not json", encoding="utf-8")
    assert last_applied(state) is None
    state.write_text('{"last_osc": "002.osc.gz"}', encoding="utf-8")
    assert last_applied(state) == "002.osc.gz"


def test_fetch_pending_downloads_and_reuses(
    tmp_path: Path, monkeypatch: object
) -> None:
    import app.jobs.osm_fetch as mod

    state = tmp_path / "osm_state.json"
    dest_dir = tmp_path / "osm"
    calls: list[str] = []

    def fake_download(url: str, dest: Path) -> None:
        calls.append(url)
        dest.write_bytes(b"fake-osc")

    monkeypatch.setattr(mod, "_download", fake_download)  # type: ignore[attr-defined]
    first = fetch_pending(_HTML, state, dest_dir)
    assert [p.name for p in first] == ["002.osc.gz"]
    assert len(calls) == 1
    # 已下载但未应用（水位未动）：复用文件不再下载
    again = fetch_pending(_HTML, state, dest_dir)
    assert [p.name for p in again] == ["002.osc.gz"]
    assert len(calls) == 1
