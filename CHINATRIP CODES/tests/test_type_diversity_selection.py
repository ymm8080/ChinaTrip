# -*- coding: utf-8 -*-
"""类型多样选点三锚（2026-11-08 成都三疑点案；同日二拍撤帽）：

①商业综合体时长保真：环球中心 240min 原样入选——开场闸（11-07
  第五拍）下 240 可落 13:00-17:00，120 压帽与「240 肯定能被任何
  一天放下」终裁相抵，已撤；
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


def test_commercial_duration_uncapped():
    mall = _cand("成都环球中心", "attraction", dur=240, rating=4.6)
    filler = _cand("望丛祠", "attraction", dur=60, rating=4.2)
    picked = PlanningAgent._deterministic_selection([mall, filler], 1, {"成都": (1, 1)})
    spec = next(p for p in picked if p["name"] == "成都环球中心")
    assert spec["duration_minutes"] == 240


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


def test_created_lane_tops_pool_order():
    # CREATED 梯（2026-11-08 拍板「低于心愿、高于其它TAG」）：手建卡
    # 置顶池序——名声分/库序更高的 TAG 卡也只能排其后。
    created = _cand("成都环球中心", "attraction", dur=240, rating=4.6)
    created["_created_lane"] = True
    ace = _cand("武侯祠", "attraction", dur=120, rating=4.9, rating_count=8000)
    picked = PlanningAgent._deterministic_selection([ace, created], 1, {"成都": (1, 1)})
    assert picked[0]["name"] == "成都环球中心"


def test_rebalance_backfill_keeps_commercial_duration():
    # 跨天回填路读库时长后不得再压帽：240 原样落卡（开场闸语义下
    # 可排 13:00-17:00，压帽与终裁相抵）。
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
    assert spec["duration_minutes"] == 240
