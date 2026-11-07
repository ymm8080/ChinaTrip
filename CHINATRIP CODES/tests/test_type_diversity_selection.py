# -*- coding: utf-8 -*-
"""类型多样选点三锚（2026-11-08 成都三疑点案）：

①商业综合体时长帽：环球中心 240min 压帽 120（240 挤爆日预算→
  untimed→_drop_untimed_from_day 移除的事故面）；
②tea 保位组：tea_experience 归 "tea" 组（人民公园 4.6 因 tier11
  排出 top-30 窗、保位网无组可归）；
③同档演出按名声分择优：夜店无评分行不再纯库序压过 4.9 分川剧院。
"""

from app.services.agent.plan import (
    PlanningAgent,
    _cand_diversity_group,
)


def _cand(name, cat, *, dur=90, rating=None, lon=104.06, lat=30.66, **kw):
    return {
        "name": name,
        "city": "成都",
        "category": cat,
        "location": {"lon": lon, "lat": lat},
        "suggested_duration_min": dur,
        "duration_minutes": dur,
        "rating": rating,
        **kw,
    }


def test_commercial_duration_cap():
    mall = _cand("成都环球中心", "attraction", dur=240, rating=4.6)
    filler = _cand("望丛祠", "attraction", dur=60, rating=4.2)
    picked = PlanningAgent._deterministic_selection([mall, filler], 1, {"成都": (1, 1)})
    spec = next(p for p in picked if p["name"] == "成都环球中心")
    assert spec["duration_minutes"] == 120


def test_tea_diversity_group_registered():
    assert _cand_diversity_group({"category": "tea_experience"}) == "tea"
    assert _cand_diversity_group({"category": "other"}) == "commercial"
    assert _cand_diversity_group({"category": "citywalk"}) == "citywalk"


def test_show_quality_beats_pool_order():
    # 库序在前、无评分的夜店 vs 4.9 分川剧院：演出席位按名声分择优。
    nightclub = _cand("PLAY HOUSE(世外桃源店)", "entertainment", dur=90)
    opera = _cand("蜀兿剧院·变脸川剧·盖碗茶", "entertainment", dur=80, rating=4.9)
    picked = PlanningAgent._deterministic_selection(
        [nightclub, opera], 1, {"成都": (1, 1)}
    )
    names = [p["name"] for p in picked]
    assert any("蜀兿剧院" in n for n in names)
    assert not any("PLAY HOUSE" in n for n in names)


def test_rebalance_backfill_caps_commercial_duration():
    # 跨天回填路曾裸读库时长绕过选点层的 commercial 帽（卡面 240 实录）。
    picked = [
        {
            "name": "钟楼",
            "city": "成都",
            "category": "attraction",
            "day": 1,
            "duration_minutes": 90,
            "location": {"lon": 104.06, "lat": 30.66},
        }
    ]
    candidates = [
        {
            "name": "成都环球中心",
            "city": "成都",
            "category": "other",
            "suggested_duration_min": 240,
            "rating": "4.7",
            "rating_count": 500,
            "location": {"lon": 104.06, "lat": 30.57},
        }
    ]
    out, _notes = PlanningAgent._rebalance_days(picked, candidates, 2, {"成都": (1, 2)})
    spec = next(s for s in out if s["name"] == "成都环球中心")
    assert spec["duration_minutes"] == 120
