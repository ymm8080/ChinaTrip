"""R18 升旗锚回归（2026-11-22 用户令「不可能没有升旗时间」）。

引擎路此前把升旗时刻只当 C-01 的**下界**、装配期**不写 fixed_sessions**：
C-04 落地地板一顶（到达 08:15），卡就排成 09:30 的中午广场——卡上没有
升旗；而卡上无锚又让下游摘钉重排/晨卡拉回/重叠推平全按普通卡处理。

三条契约（全部离线，flag 真值显式注入或补丁，不碰库）：
① 有天安门广场必有升旗时刻，且卡开始 == 真值，fixed_sessions 落卡；
② 当天物理赶不上（落地晚于升旗）→ 换天，而不是排一张没旗时的广场卡；
③ 没有旗时数据时绝不编造——不落锚、按既有晨间兜底排。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import time

import pytest

from app.services.itinerary.models import VisitItem
from app.services.trip_solver.assembly import assemble
from app.services.trip_solver.inputs.enrich import enrich
from app.services.trip_solver.model.solve import solve_snapshot
from app.services.trip_solver.snapshot import default_golden_path, load_golden

G01 = default_golden_path()
FLAGS = {1: 430, 2: 431}  # 2026-11-25 07:10 / 11-26 07:11（真库实测值）


def _patch_flag_table(monkeypatch, table: dict[int, int]) -> None:
    """装配层懒导入同一函数——补丁即等于「库里有/没有真值」。"""
    monkeypatch.setattr(
        "app.services.flag_schedule.flag_minutes_by_day",
        lambda *a, **k: dict(table),
    )


def _plan(monkeypatch, table=FLAGS, **request_overrides):
    _patch_flag_table(monkeypatch, table)
    snapshot, _expect, _prov = load_golden(G01)
    if request_overrides:
        snapshot = replace(
            snapshot, request=replace(snapshot.request, **request_overrides)
        )
    solution = solve_snapshot(enrich(snapshot, flag_times=table))
    plan = assemble(solution, snapshot)
    return plan


def _sunrise_cards(plan):
    return [
        (d.day, i)
        for d in plan.days
        for i in d.items
        if isinstance(i, VisitItem)
        and str(getattr(i, "best_visit_time", "") or "") == "sunrise"
    ]


def test_sunrise_card_is_pinned_to_the_flag_minute(monkeypatch):
    """① 卡开始 == 库内升旗时刻，且 fixed_sessions 落卡（下游保护认账）。"""
    plan = _plan(monkeypatch)
    cards = _sunrise_cards(plan)
    assert cards, "天安门广场必须在排（golden g01 必去）"
    for day, card in cards:
        flag = time(FLAGS[day] // 60, FLAGS[day] % 60)
        assert card.start_time == flag, (day, card.start_time, flag)
        assert card.fixed_sessions == [flag], (day, card.fixed_sessions)


def test_arrival_after_sunrise_moves_the_card_to_another_day(monkeypatch):
    """② 落地 08:15 赶不上 07:10——换天，不排「没有升旗的广场」。"""
    plan = _plan(monkeypatch, day1_start="08:15")
    cards = _sunrise_cards(plan)
    assert cards, "换天而不是消失"
    assert all(day != 1 for day, _ in cards), [(d, str(i.start_time)) for d, i in cards]
    day, card = cards[0]
    assert card.start_time == time(FLAGS[day] // 60, FLAGS[day] % 60)
    assert card.fixed_sessions == [card.start_time]


def test_without_flag_data_no_anchor_is_fabricated(monkeypatch):
    """③ 无真值（无出发日期/库空）→ 不落锚，保持既有晨间兜底。"""
    plan = _plan(monkeypatch, table={})
    for _day, card in _sunrise_cards(plan):
        assert not card.fixed_sessions


def test_flag_anchor_survives_response_projection(monkeypatch):
    """出站投影不清锚（H5 显示「升旗 07:10」靠 fixed_sessions）。"""
    from app.api.plan import _plan_for_response

    plan = _plan(monkeypatch)
    body = _plan_for_response(plan)
    hits = [
        i
        for d in body.days
        for i in d.items
        if str(getattr(i, "best_visit_time", "") or "") == "sunrise"
    ]
    assert hits
    for item in hits:
        assert item.fixed_sessions, item.name
        assert item.start_time == item.fixed_sessions[0]


@pytest.mark.parametrize("days", [1, 2])
def test_flag_table_absent_when_no_start_date(monkeypatch, days):
    """无出发日期 → flag_minutes_by_day 空（不编造钟点）。"""
    from app.services.flag_schedule import flag_minutes_by_day

    assert flag_minutes_by_day(None, days) == {}
    assert flag_minutes_by_day("2026-11-25", 0) == {}


def test_changing_start_date_reanchors_the_flag(monkeypatch):
    """R18 续：改出发日期 → 旗时跟着改，旧锚不得冻住（11-25 07:10 → 12-21 07:32）。"""
    from app.services.agent.plan import _apply_flag_schedule

    table = {"2026-11-25": time(7, 10), "2026-12-21": time(7, 32)}
    monkeypatch.setattr(
        "app.services.flag_schedule.get_flag_time",
        lambda date_iso, category="morning", **k: table.get(str(date_iso)),
    )
    plan = _plan(monkeypatch)
    card = _sunrise_cards(plan)[0][1]
    assert card.fixed_sessions == [time(7, 10)], card.fixed_sessions

    plan.start_date = "2026-12-21"
    _apply_flag_schedule(plan)
    assert card.fixed_sessions == [time(7, 32)], card.fixed_sessions
    assert card.start_time == time(7, 32), card.start_time


def test_missing_flag_time_is_disclosed(monkeypatch):
    """R18 续（2026-11-22 拍板「we need msg」）：查表落空不再静默——
    assumptions 明说「暂按常规晨间时段（未按升旗时刻锚定）」。"""
    from app.services.agent.plan import _apply_flag_schedule

    _patch_flag_table(monkeypatch, {})
    monkeypatch.setattr(
        "app.services.flag_schedule.get_flag_time", lambda *a, **k: None
    )
    plan = _plan(monkeypatch, table={})
    _apply_flag_schedule(plan)
    assert any("暂按常规晨间时段" in str(a) for a in plan.assumptions)
    assert any("未按升旗时刻锚定" in str(a) for a in plan.assumptions)


def test_no_departure_date_flag_disclosure(monkeypatch):
    """无出发日期同理：披露「以出行当日官方公告为准」，不装作已锚定。"""
    from app.services.agent.plan import _apply_flag_schedule

    _patch_flag_table(monkeypatch, {})
    plan = _plan(monkeypatch, table={})
    plan.start_date = None
    _apply_flag_schedule(plan)
    assert any("尚未确定出发日期" in str(a) for a in plan.assumptions)


def test_date_moved_to_uncovered_year_keeps_anchor_but_discloses(monkeypatch):
    """改到公告未覆盖的年份：旧锚留卡（有真值不回退、不编造），但必须披露。"""
    from app.services.agent.plan import _apply_flag_schedule

    table = {"2026-11-25": time(7, 10)}
    monkeypatch.setattr(
        "app.services.flag_schedule.get_flag_time",
        lambda date_iso, category="morning", **k: table.get(str(date_iso)),
    )
    plan = _plan(monkeypatch)
    plan.start_date = "2027-02-06"
    _apply_flag_schedule(plan)
    card = _sunrise_cards(plan)[0][1]
    assert card.fixed_sessions == [time(7, 10)], card.fixed_sessions
    assert any("升旗时刻暂缺" in str(a) for a in plan.assumptions)
