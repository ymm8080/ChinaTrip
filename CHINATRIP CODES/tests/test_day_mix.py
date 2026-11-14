"""日间混排闸（2026-11-13 用户「上海野生动物园离上海中心太远，不应该安排」）。

城心簇日（≥2 件距城心 ≤10km）不收远郊件（>25km）；远郊件改投无城心件的
日子，无日可投则移出并留痕。单锚+远点仍算正常一日游（都江堰/长城形态）。
"""

from __future__ import annotations

from app.services.agent.plan import PlanningAgent


def _cand(name, lon, lat, minutes=90, city="上海"):
    return {
        "name": name,
        "city": city,
        "category": "attraction",
        "suggested_duration_min": minutes,
        "location": {"lon": lon, "lat": lat},
    }


def test_far_sight_does_not_share_day_with_city_cluster():
    cands = [
        _cand("东方明珠", 121.4998, 31.2397, 165),
        _cand("外滩", 121.4903, 31.2398, 120),
        _cand("南京东路步行街", 121.4823, 31.2367),
        _cand("上海野生动物园", 121.7133, 31.0469, 240),
    ]
    items = PlanningAgent._deterministic_selection(cands, 2, {"上海": (1, 2)})
    zoo = next((it for it in items if it["name"] == "上海野生动物园"), None)
    city_names = ("东方明珠", "外滩", "南京东路步行街")
    city_days = {it["day"] for it in items if it["name"] in city_names}
    if zoo is not None:
        assert zoo["day"] not in city_days  # 远郊件不与城心簇同日


def test_far_point_dropped_when_only_city_day_left():
    """严格口径：城心件与远郊件永不同日；无合规日则远郊件移出留痕。"""
    cands = [
        _cand("都江堰景区", 103.62, 30.90, 240, city="成都"),
        _cand("宽窄巷子", 104.06, 30.66, 90, city="成都"),
    ]
    notes: list[str] = []
    items = PlanningAgent._deterministic_selection(
        cands, 1, {"成都": (1, 1)}, notes=notes
    )
    names = {it["name"] for it in items}
    assert names == {"宽窄巷子"}
    assert any("离城心太远" in str(n) for n in notes)
