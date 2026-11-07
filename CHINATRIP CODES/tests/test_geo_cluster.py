"""geo 聚类 + 计划级查全率（§6.1 / §8.2.6）测试。"""

from app.services.itinerary.geo import area_labels, cluster_days


def _c(name, lon, lat, ba=None):
    return {
        "name": name,
        "business_area": ba,
        "location": {"lon": lon, "lat": lat},
    }


def test_cluster_days_groups_by_geography():
    cands = [
        _c("东1", 121.50, 31.24, "外滩"),
        _c("东2", 121.51, 31.24, "外滩"),
        _c("西1", 121.20, 31.20, "虹桥"),
        _c("西2", 121.19, 31.21, "虹桥"),
        _c("无坐标", None, None),
    ]
    clusters = cluster_days(cands, 2)
    assert clusters[0] == clusters[1]  # 同在东侧
    assert clusters[2] == clusters[3]  # 同在西侧
    assert clusters[0] != clusters[2]  # 东西分离
    assert clusters[4] is None  # 无坐标不参与

    labels = area_labels(cands, clusters)
    east = labels[clusters[0]]
    west = labels[clusters[2]]
    assert {east, west} == {"外滩", "虹桥"}


def test_cluster_days_degenerate_inputs():
    assert cluster_days([], 3) == []
    assert cluster_days([{"location": None}], 2) == [None]
    assert cluster_days([_c("a", 1, 1)], 0) == [None]


def test_cluster_days_distance_cap_10km():
    # 片区归属距离上限（2026-11-07 用户拍板「geo_cluster 距离上限 10 公
    # 里」）：k 耗尽后 55km 离群点不再被拖进最近簇（旧版大足石刻挂进成
    # 都市区簇=「同片区同天」假象）→ None 走无归属路径；近点不受影响。
    cands = [
        _c("城1", 104.06, 30.66),
        _c("城2", 104.07, 30.66),  # ~1km，正常归属
        _c("远点", 104.55, 30.66),  # ~47km，k=1 时无处安放
    ]
    assert cluster_days(cands, 1) == [0, 0, None]
    # k=2 时远点自成一簇（种子），归属正常
    assert cluster_days(cands, 2) == [0, 0, 1]


def test_cluster_days_cap_boundary_just_under():
    # 边界：~9km 点仍归属（上限内），~11km 不归属
    cands = [
        _c("锚", 104.06, 30.66),
        _c("近", 104.06, 30.74),  # ~8.9km
        _c("远", 104.06, 30.76),  # ~11.1km
    ]
    assert cluster_days(cands, 1) == [0, 0, None]


def test_area_labels_fallback_to_index():
    cands = [_c("a", 121.5, 31.2), _c("b", 121.5, 31.21)]
    clusters = cluster_days(cands, 1)
    assert area_labels(cands, clusters)[0].startswith("片区")


# --- 覆盖率 + 天气建议（§8.2.6 / §8.1.4） -----------------------------------


def test_premium_coverage_gaps_flags_unpicked_5a():
    from app.services.itinerary.coverage import premium_coverage_gaps

    candidates = [
        {"name": "故宫", "tags": ["5a"]},
        {"name": "外滩", "tags": []},
        {"name": "莫高窟", "tags": ["unesco", "5a"]},
    ]
    gaps = premium_coverage_gaps(["外滩"], candidates)
    assert {g["name"] for g in gaps} == {"故宫", "莫高窟"}


def test_rain_swap_advice_only_when_rain_and_outdoor():
    from app.services.itinerary.coverage import rain_swap_advice

    day = [{"name": "广场", "rain_ok": "no"}, {"name": "博物馆", "rain_ok": "yes"}]
    assert rain_swap_advice("小雨", day) is not None
    assert "对调" in rain_swap_advice("小雨", day)
    assert rain_swap_advice("晴", day) is None  # 无雨不提
    assert rain_swap_advice("小雨", [{"name": "馆", "rain_ok": "yes"}]) is None


def test_premium_coverage_gaps_shows_all_by_default():
    # 2026-10-31 用户拍板：白名单只显示前 3 条被质疑——默认全量，
    # max_missing 仅供测试收窄
    from app.services.itinerary.coverage import premium_coverage_gaps

    candidates = [{"name": f"5a景区{i}", "tags": ["5a"]} for i in range(1, 6)]
    gaps = premium_coverage_gaps(["外滩"], candidates)
    assert [g["name"] for g in gaps] == [f"5a景区{i}" for i in range(1, 6)]
    # 收窄参数仍可用
    assert len(premium_coverage_gaps(["外滩"], candidates, max_missing=2)) == 2


def test_premium_coverage_gaps_flags_silk_road_component():
    # 2026-11-02 大雁塔事故：丝路点段代表行 tags 只有 unesco_silk_road
    # （无 5a/unesco 字面量）时，白名单披露层同样要点名。
    from app.services.itinerary.coverage import premium_coverage_gaps

    candidates = [
        {"name": "大雁塔大唐芙蓉园景区", "tags": ["unesco_silk_road"]},
        {"name": "昌平区明十三陵景区", "tags": ["unesco_ming_tombs"]},
    ]
    gaps = premium_coverage_gaps(["未央宫遗址"], candidates)
    assert [g["name"] for g in gaps] == ["大雁塔大唐芙蓉园景区", "昌平区明十三陵景区"]
    assert gaps[0]["tags"] == ["unesco_silk_road"]
    assert gaps[1]["tags"] == ["unesco_ming_tombs"]


def test_source_tier_silk_road_component_top_ladder():
    # 丝路点段（unesco_silk_road）与全量世遗同档 tier=1，压过 5A——
    # 世界遗产有更高的优先权（2026-11-02 大雁塔事故）。
    from app.services.agent.plan import _source_tier

    assert _source_tier({"source": "relicpark", "tags": ["unesco_silk_road"]}) == 1
    assert _source_tier({"source": "5a", "tags": ["unesco_ming_tombs"]}) == 1
    assert _source_tier({"source": "5a", "tags": ["unesco_karst"]}) == 1
    assert (
        _source_tier({"source": "5a", "tags": ["5a", "intl", "unesco_silk_road"]}) == 1
    )
    assert _source_tier({"source": "5a", "tags": ["5a"]}) == 2
    assert _source_tier({"source": "relicpark", "tags": ["relicpark"]}) == 11
