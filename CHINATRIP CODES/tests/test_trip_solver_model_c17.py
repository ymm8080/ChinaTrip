from __future__ import annotations

from pathlib import Path

from app.services.trip_solver.inputs.enrich import enrich
from app.services.trip_solver.model.c17_city_days import city_day_windows
from app.services.trip_solver.model.solve import solve_snapshot
from app.services.trip_solver.snapshot import default_golden_path, load_golden

G14 = Path(default_golden_path()).with_name("g14_city_days_windows.json")


def test_city_day_windows_mirror_legacy_split():
    # 常规多城：出发城不吃天，真实目的地按请求序连续切窗
    assert city_day_windows(["北京", "杭州", "上海"], 5, {"杭州": 2, "上海": 3}) == {
        "杭州": (1, 2),
        "上海": (3, 5),
    }
    # 闭合行程：尾城=返程标记，末位真实目的地吃满到 days
    assert city_day_windows(
        ["北京", "杭州", "上海", "北京"], 3, {"杭州": 1, "上海": 1, "北京": 1}
    ) == {"杭州": (1, 1), "上海": (2, 3)}
    # 预算溢出：后位城市被钳到剩余天
    assert city_day_windows(["北京", "杭州", "上海"], 4, {"杭州": 3, "上海": 3}) == {
        "杭州": (1, 3),
        "上海": (4, 4),
    }
    # 预算不足：末位吃满到 days 吸收余天
    assert city_day_windows(["北京", "杭州", "上海"], 5, {"杭州": 1, "上海": 1}) == {
        "杭州": (1, 1),
        "上海": (2, 5),
    }
    # 单城：全日程窗
    assert city_day_windows(["上海"], 2, {"上海": 2}) == {"上海": (1, 2)}


def test_c17_locks_candidates_into_city_windows():
    snapshot, _expect, _prov = load_golden(str(G14))
    enriched = enrich(snapshot)
    sol = solve_snapshot(enriched)
    assert sol.status in ("OPTIMAL", "FEASIBLE"), sol.status

    by_cid = {c.cid: c for c in snapshot.candidates}
    names_placed = {by_cid[i.cid].name for i in sol.items}
    for item in sol.items:
        city = by_cid[item.cid].city
        if city == "杭州":
            assert item.day in (1, 2)
        elif city == "上海":
            assert item.day in (3, 4, 5)
        else:
            raise AssertionError("窗外城市被排入：%s day%s" % (city, item.day))
    # 必去全覆盖 + 出发城候选灭活（legacy：出发城不收候选）
    assert not sol.unplaced
    assert "故宫博物院" not in names_placed
    for m in ("西湖风景名胜区", "灵隐寺", "外滩", "豫园"):
        assert m in names_placed


def test_c17_absent_keeps_free_allocation_untouched():
    """缺省 city_days=() → 零约束：多城语料 g10 行为不变（自由分配）。"""
    g10 = Path(default_golden_path()).with_name("g10_city_coherence.json")
    snapshot, _e, _p = load_golden(str(g10))
    assert snapshot.request.city_days == ()
    enriched = enrich(snapshot)
    sol = solve_snapshot(enriched)
    assert sol.status in ("OPTIMAL", "FEASIBLE"), sol.status
    assert not sol.unplaced
