"""backfill_best_visit 作业单测：假 session + 注入 stub，不碰真实 DB."""

from __future__ import annotations

from types import SimpleNamespace

from app.jobs.backfill_best_visit import (
    _norm_city,
    apply_stage,
    select_targets,
)


def _row(
    name_zh: str = "测试景点",
    *,
    city: str = "重庆",
    category: str | None = None,
    opening_hours: str | None = None,
    status: str = "active",
    best_visit_time: str | None = None,
    best_visit_time_source: str | None = None,
):
    return SimpleNamespace(
        name_zh=name_zh,
        city=city,
        category=category,
        opening_hours=opening_hours,
        status=status,
        best_visit_time=best_visit_time,
        best_visit_time_source=best_visit_time_source,
    )


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def limit(self, n):
        return self

    def all(self):
        return list(self._rows)


class _FakeSession:
    def __init__(self, rows=None):
        self._rows = list(rows or [])
        self.commits = 0

    def query(self, model):
        return _FakeQuery(self._rows)

    def commit(self):
        self.commits += 1


# --- select_targets -------------------------------------------------------


def test_select_targets_city_strips_shi_suffix():
    session = _FakeSession(
        [
            _row("洪崖洞", city="重庆市"),
            _row("解放碑", city="重庆"),
            _row("宽窄巷子", city="成都市"),
        ]
    )
    rows = select_targets(session, "heuristic", "重庆", 10)
    assert {r.name_zh for r in rows} == {"洪崖洞", "解放碑"}


def test_select_targets_skips_non_empty_and_inactive():
    session = _FakeSession(
        [
            _row("已填", best_visit_time="evening", best_visit_time_source="ctrip"),
            _row("停用", status="inactive"),
            _row("可写"),
        ]
    )
    rows = select_targets(session, "heuristic", None, 10)
    assert [r.name_zh for r in rows] == ["可写"]


def test_select_targets_llm_excludes_heuristic_marked():
    session = _FakeSession(
        [
            _row(
                "规则已标",
                best_visit_time="evening",
                best_visit_time_source="heuristic",
            ),
            _row("llm可写", best_visit_time="any", best_visit_time_source=None),
        ]
    )
    rows = select_targets(session, "llm", None, 10)
    assert [r.name_zh for r in rows] == ["llm可写"]


def test_select_targets_respects_limit():
    session = _FakeSession([_row(f"poi{i}") for i in range(5)])
    assert len(select_targets(session, "heuristic", None, 3)) == 3


def test_norm_city():
    assert _norm_city("重庆市") == "重庆"
    assert _norm_city("重庆") == "重庆"
    assert _norm_city(None) == ""


# --- heuristic stage ------------------------------------------------------


def test_heuristic_hit_writes_source():
    session = _FakeSession()
    row = _row("两江夜游")
    stats = apply_stage(
        session,
        [row],
        "heuristic",
        rules_fn=lambda name, cat: "evening",
        hours_fn=lambda hours: None,
    )
    assert stats["targets"] == 1
    assert stats["heuristic_filled"] == 1
    assert row.best_visit_time == "evening"
    assert row.best_visit_time_source == "heuristic"
    assert session.commits == 1


def test_heuristic_falls_back_to_hours():
    hours_fn_calls = []

    def hours_fn(hours):
        hours_fn_calls.append(hours)
        return "morning"

    session = _FakeSession()
    row = _row("无名景点", opening_hours="06:00-10:00")
    stats = apply_stage(
        session,
        [row],
        "heuristic",
        rules_fn=lambda name, cat: None,
        hours_fn=hours_fn,
    )
    assert hours_fn_calls == ["06:00-10:00"]
    assert stats["heuristic_filled"] == 1
    assert row.best_visit_time == "morning"
    assert row.best_visit_time_source == "heuristic"


def test_heuristic_no_signal_counts():
    session = _FakeSession()
    row = _row("普通景点")
    stats = apply_stage(
        session,
        [row],
        "heuristic",
        rules_fn=lambda name, cat: None,
        hours_fn=lambda hours: None,
    )
    assert stats["no_signal"] == 1
    assert stats["heuristic_filled"] == 0
    assert row.best_visit_time is None
    assert session.commits == 0


def test_non_empty_row_never_overwritten():
    """铁律只升不降：已有 evening 不被规则覆盖，计 skipped_not_empty."""
    session = _FakeSession()
    row = _row(
        "两江夜游",
        best_visit_time="evening",
        best_visit_time_source="ctrip",
    )
    stats = apply_stage(
        session,
        [row],
        "heuristic",
        rules_fn=lambda name, cat: "morning",  # 恶意试图降级
        hours_fn=lambda hours: "morning",
    )
    assert stats["skipped_not_empty"] == 1
    assert stats["heuristic_filled"] == 0
    assert row.best_visit_time == "evening"
    assert row.best_visit_time_source == "ctrip"
    assert session.commits == 0


def test_apply_stage_rejects_unknown_stage():
    try:
        apply_stage(_FakeSession(), [], "ctrip")
    except ValueError as exc:
        assert "ctrip" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_apply_stage_llm_requires_llm_fn():
    try:
        apply_stage(_FakeSession(), [_row()], "llm")
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError")


# --- llm stage ------------------------------------------------------------


def test_llm_valid_slot_written():
    session = _FakeSession()
    row = _row("鹅岭公园夜景")
    stats = apply_stage(
        session,
        [row],
        "llm",
        llm_fn=lambda name, cat: '{"slot": "evening"}',
        batch_sleep=0,
    )
    assert stats["llm_filled"] == 1
    assert row.best_visit_time == "evening"
    assert row.best_visit_time_source == "llm"


def test_llm_out_of_enum_is_invalid():
    session = _FakeSession()
    row = _row("某景点")
    stats = apply_stage(
        session,
        [row],
        "llm",
        llm_fn=lambda name, cat: '{"slot": "midnight"}',
        batch_sleep=0,
    )
    assert stats["invalid"] == 1
    assert stats["llm_filled"] == 0
    assert row.best_visit_time is None
    assert session.commits == 0


def test_llm_bad_json_is_invalid():
    session = _FakeSession()
    row = _row("某景点")
    stats = apply_stage(
        session,
        [row],
        "llm",
        llm_fn=lambda name, cat: "抱歉，我无法回答这个问题",
        batch_sleep=0,
    )
    assert stats["invalid"] == 1
    assert row.best_visit_time is None


def test_llm_any_is_no_signal():
    session = _FakeSession()
    row = _row("普通商场")
    stats = apply_stage(
        session,
        [row],
        "llm",
        llm_fn=lambda name, cat: '{"slot": "any"}',
        batch_sleep=0,
    )
    assert stats["no_signal"] == 1
    assert stats["llm_filled"] == 0
    assert row.best_visit_time is None


def test_llm_request_failure_is_no_signal():
    session = _FakeSession()
    row = _row("某景点")
    stats = apply_stage(
        session,
        [row],
        "llm",
        llm_fn=lambda name, cat: None,
        batch_sleep=0,
    )
    assert stats["no_signal"] == 1
    assert stats["invalid"] == 0


def test_llm_tolerates_code_fence_and_prose():
    session = _FakeSession()
    row = _row("南山一棵树观景台")
    stats = apply_stage(
        session,
        [row],
        "llm",
        llm_fn=lambda name, cat: '好的，判断如下：```json\n{"slot": "sunset"}\n```',
        batch_sleep=0,
    )
    assert stats["llm_filled"] == 1
    assert row.best_visit_time == "sunset"


def test_llm_non_empty_row_skipped_and_no_llm_call():
    calls = []

    def llm_fn(name, cat):
        calls.append(name)
        return '{"slot": "evening"}'

    session = _FakeSession()
    row = _row("已定", best_visit_time="morning", best_visit_time_source="ctrip")
    stats = apply_stage(session, [row], "llm", llm_fn=llm_fn, batch_sleep=0)
    assert stats["skipped_not_empty"] == 1
    assert calls == []
    assert row.best_visit_time == "morning"
