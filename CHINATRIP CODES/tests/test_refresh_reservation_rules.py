"""refresh_reservation_rules 周更作业测试：五关校验 + mock 跳过 + 表写桩。"""

import json

from app.jobs import refresh_reservation_rules as mod

GOOD_RULE = {
    "advance_days": 7,
    "release": "20:00",
    "channel": "「故宫博物院」微信小程序",
    "foreigner_friendly": "yes",
    "note": "周一闭馆（法定节假日除外）",
    "source": "https://ticket.dpm.org.cn",
}


def _settings(backend="zhipu"):
    class S:
        llm_backend = backend
        glm_model_flash = "glm-5.3-flash"
        glm_base_url = "https://x"
        glm_api_key = "k"
        glm_timeout_seconds = 30

    return S()


# --- 五关校验 -----------------------------------------------------------------


def test_gates_accept_official_shape():
    assert mod._gates(GOOD_RULE) == []


def test_gates_reject_bad_days_release_source():
    bad = dict(GOOD_RULE, advance_days=0, release="25:00", source="不是URL")
    problems = mod._gates(bad)
    assert any("advance_days" in p for p in problems)
    assert any("release" in p for p in problems)
    assert any("source" in p for p in problems)
    # 天数上限防呆（30 天外视为解析污染）
    over = mod._gates(dict(GOOD_RULE, advance_days=99))
    assert any("advance_days" in p for p in over)


def test_gates_reject_non_int_days():
    assert any(
        "advance_days" in p for p in mod._gates(dict(GOOD_RULE, advance_days="7"))
    )


# --- main 流 -----------------------------------------------------------------


def test_main_skips_on_mock_backend(capsys, monkeypatch):
    monkeypatch.setattr(mod, "_get_settings", lambda: _settings(backend="mock"))
    assert mod.main([]) == 0
    assert "skipped" in capsys.readouterr().out


def test_main_reports_diff_and_skips_db_on_dry_run(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(mod, "_get_settings", lambda: _settings())
    monkeypatch.setattr(
        mod, "_check_one", lambda s, name, city, timeout: (dict(GOOD_RULE), {})
    )  # 故宫 7 天 == 名单 7 天 → 无 diff；再放一个 3 天的看 diff
    calls = {"apply": 0}

    def _fake_apply(factory, name, rule):
        calls["apply"] += 1
        return True

    monkeypatch.setattr(mod, "_apply_db", _fake_apply)
    monkeypatch.setattr(mod, "_DESIGN", tmp_path)
    rc = mod.main(["--dry-run"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["errors"] == 0 and out["db_rows_updated"] == 0
    assert calls["apply"] == 0  # dry-run 不碰表
    assert (tmp_path / out["snapshot"].split("/")[-1]).exists()


def test_apply_db_updates_matching_rows():
    class _Row:
        def __init__(self):
            self.name_zh = "故宫"
            self.reservation_required = None
            self.reservation_advance_days = None
            self.booking_url = None

    _rows = [_Row()]

    class _Q:
        def filter(self, *a, **k):
            return self

        def all(self):
            return _rows  # 同一批实例：断言才能看到写入

    class _S:
        def query(self, *a, **k):
            return _Q()

        def commit(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class _F:
        def __call__(self):
            return _S()

    assert mod._apply_db(_F(), "故宫", GOOD_RULE) is True
    row = _rows[0]
    assert row.reservation_required is True
    assert row.reservation_advance_days == 7
    assert row.booking_url == GOOD_RULE["source"]
