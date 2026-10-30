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
