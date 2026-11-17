# -*- coding: utf-8 -*-
"""降级披露拆分（2026-11-17）：真降级才说「求解器未收敛」。

背景：生成收口旧口径 `degraded OR 有未排卡` 都追加同一句「求解器未收敛，
时间已按顺序兜底排列」——solver 正常出解、只是个别卡按顺序留位的行程也
被谎称为未收敛（live 全勤披露的大头）。e6133a4 修掉真降级根因后，本拆分
保证披露与事实一致。
"""

from app.services.agent.plan import _append_solve_degradation_notes
from app.services.itinerary.models import DayPlan, ItineraryPlan


def _plan():
    return ItineraryPlan(
        itinerary_id="it-dg",
        cities=["上海"],
        days=[DayPlan(day=1, base_city="上海", items=[])],
        assumptions=[],
    )


def test_true_degradation_keeps_old_line():
    plan = _plan()
    _append_solve_degradation_notes(plan, degraded=True, had_untimed=True)
    assert any("求解器未收敛" in a for a in plan.assumptions)
    assert not any("按游览顺序留位" in a for a in plan.assumptions)


def test_untimed_only_gets_honest_line_not_solver_failure():
    plan = _plan()
    _append_solve_degradation_notes(plan, degraded=False, had_untimed=True)
    assert not any("求解器未收敛" in a for a in plan.assumptions)
    assert any("按游览顺序留位" in a for a in plan.assumptions)


def test_clean_solve_is_silent():
    plan = _plan()
    _append_solve_degradation_notes(plan, degraded=False, had_untimed=False)
    assert plan.assumptions == []
