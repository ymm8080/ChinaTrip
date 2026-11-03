"""同站双卡清扫测试（2026-11-04 全库 268 城 9898 行扫描定稿）。

池内存活 357 对隐患里可规则化的两大族收口：
①「·」复合挂牌族——城墙·碑林历史文化景区(5a_304) vs 西安城墙(intl_0075)
  同日双卡实录（2.18km），含光门城墙遗址博物馆(959m) 同族；闸 2.5km。
②国家考古遗址公园同址族——万寿岩/仰韶村/城头山/大明宫国家考古遗址公园
  vs 同址 文旅小镇/博物馆/旅游景区 行（relicpark 与 4a/5a 多档并存）；
  闸走同馆档 10km（大明宫类园区级跨度）。
反例锁死：物理相邻确非同站（大雁塔 vs 陕历博 ~1km）、同区竞争场所
（温泉对）、0m 坐标债遗址簇（巴音郭楞）、跨区系列名（峨眉山—乐山大佛
分段 vs 独立乐山大佛行 30km 天然拦住）不得误并。
"""

from __future__ import annotations

from app.services.agent.plan import (
    _cand_twin,
    _composite_dup,
    _name_dup,
    _relic_park_dup,
)


def _c(name, lon, lat, cat="attraction"):
    return {"name": name, "category": cat, "location": {"lon": lon, "lat": lat}}


# --- ① 复合挂牌族 -----------------------------------------------------------


def test_composite_wall_pair():
    """城墙·碑林 vs 西安城墙：段「城墙」命中，2.18km 实录距离过 2.5km 闸。"""
    a = _c("城墙·碑林历史文化景区", 108.9417, 34.2568)
    b = _c("西安城墙", 108.9290, 34.2759)  # 实测 ~2.1km
    assert _composite_dup(a["name"], b["name"]) is True
    assert _cand_twin(a, b) is True


def test_composite_hanguang_museum():
    """含光门城墙遗址博物馆 vs 城墙·碑林：墙上场馆同段命中（959m）。"""
    a = _c("含光门城墙遗址博物馆", 108.9360, 34.2490)
    b = _c("城墙·碑林历史文化景区", 108.9417, 34.2568)
    assert _cand_twin(a, b) is True


def test_composite_geo_gate_blocks_far_series():
    """跨区系列名不并：复合挂牌闸 2.5km，峨眉山锚点 vs 乐山大佛行 ~30km。"""
    a = _c("峨眉山—乐山大佛", 103.4400, 29.5500)  # 世遗系列行锚峨眉山
    b = _c("乐山大佛", 103.7720, 29.5450)  # 实际大佛 ~31km
    assert _cand_twin(a, b) is False


def test_composite_generic_segment_ignored():
    """泛词段不受理：段剥尾巴后为泛词（文化/旅游类）不判同站。"""
    a = _c("甲山·文化", 108.9, 34.2)
    b = _c("乙地文化中心", 108.9, 34.2)
    assert _composite_dup(a["name"], b["name"]) is False


# --- ② 考古遗址公园同址族 ---------------------------------------------------


def test_relic_park_xian_trio():
    """大明宫双卡（relicpark_0054 vs 5a_306 曾同计划在排）：园区级跨度过 10km 闸。"""
    a = _c("大明宫国家考古遗址公园", 108.9510, 34.2850)
    b = _c("大明宫旅游景区", 108.9430, 34.2680)  # 跨园区 ~3km
    assert _relic_park_dup(a["name"], b["name"]) is True
    assert _cand_twin(a, b) is True


def test_relic_park_swept_pairs():
    """清扫实录四对：万寿岩/仰韶/城头山 遗址公园 vs 同址文旅小镇/博物馆/景区。"""
    pairs = [
        ("三明市万寿岩文旅小镇景区", "万寿岩国家考古遗址公园", 806),
        ("仰韶博物馆", "仰韶村国家考古遗址公园", 425),
        ("常德市城头山旅游景区", "城头山国家考古遗址公园", 994),
    ]
    for x, y, _m in pairs:
        assert _name_dup(x, y) is True, (x, y)


def test_relic_park_different_sites_not_merged():
    """不同遗址不并：遗址名 ≥2 字独立，无包含关系不受理。"""
    assert _relic_park_dup("仰韶村国家考古遗址公园", "城头山国家考古遗址公园") is False


# --- 反例：物理相邻确非同站（宁漏勿误） -------------------------------------


def test_huaqing_family_bucket():
    """华清宫/华清池历史更名双挂牌（5a_297 vs intl_0079）同站收桶。"""
    a = _c("华清宫", 109.2120, 34.3620)
    b = _c("临潼区华清池景区", 109.2125, 34.3625)
    assert _cand_twin(a, b) is True


def test_huaqing_family_not_cross_site():
    """家族桶不跨站：华清宫 vs 无关行不误并。"""
    assert _name_dup("华清宫", "骊山风景名胜区") is False


def test_adjacent_distinct_sites_not_merged():
    """大雁塔 vs 陕西历史博物馆 ~1km 但确是两站；城墙·碑林段不命中。"""
    a = _c("大雁塔大唐芙蓉园景区", 108.9640, 34.2180)
    b = _c("陕西历史博物馆", 108.9550, 34.2220)
    assert _cand_twin(a, b) is False


def test_zero_dist_placeholder_cluster_not_merged():
    """巴音郭楞 0m 坐标债遗址簇：不同遗址同名县城锚点，名字通道不命中。"""
    a = _c("阔纳协海尔古城遗址", 86.1500, 41.7600)
    b = _c("霍拉山佛寺遗址", 86.1500, 41.7600)
    assert _cand_twin(a, b) is False


def test_same_area_competing_venues_not_merged():
    """同区竞争场所不并：两家不同温泉度假村 874m。"""
    a = _c("咸宁市楚天瑶池温泉度假村", 114.3220, 29.8410)
    b = _c("咸宁市温泉谷度假区", 114.3290, 29.8480)
    assert _cand_twin(a, b) is False


# --- ③ 组装层/行程级合并入口（_same_visit，2026-11-04 城墙双卡回归）----------


def _wall_cards():
    """城墙双卡实录（会话 26037cd0…，库真身坐标 2.17km）：
    正选 v33=5a_304 城墙·碑林历史文化景区(day4)、后进 v36=lp 西安城墙(day5)。"""
    from app.services.itinerary.models import GeoPoint, VisitItem

    wall_beilin = VisitItem(
        item_id="v33",
        name="城墙·碑林历史文化景区",
        poi_id="5a_304",
        category="attraction",
        city="西安",
        location=GeoPoint(lon=108.94052490245161, lat=34.25687582300908),
        day=4,
    )
    wall_lp = VisitItem(
        item_id="v36",
        name="西安城墙",
        poi_id="lonelyplanet:西安:西安城墙",
        category="attraction",
        city="西安",
        location=GeoPoint(lon=108.947110464377, lat=34.275703457106104),
        day=5,
    )
    return wall_beilin, wall_lp


def test_same_visit_blocks_late_wall_card():
    """正选 5a_304 城墙·碑林已在册，组装层再遇 lp 西安城墙必须并掉。

    行程级唯一入口（_dedupe_visit_keepers / dedupe_plan_visits）走
    _same_visit——2026-11-04 前「·」复合通道只挂在 _name_dup
    （_cand_twin/_dup_blocks_item 池/回填层），_same_visit 漏挂，
    两卡全数过闸同计划双卡。修复后通道齐平：2.17km < 复合闸 2.5km。"""
    from app.services.agent.plan import _dedupe_visit_keepers, _same_visit

    wall_beilin, wall_lp = _wall_cards()
    assert _same_visit(wall_beilin, wall_lp) is True
    keepers, dropped = _dedupe_visit_keepers([wall_beilin, wall_lp])
    assert dropped == ["西安城墙"]
    # 正选留卡：先到先得平手（rank 同分），5a_304 是 selection tier 序先行者
    assert [k.poi_id for k in keepers] == ["5a_304"]


def test_same_visit_relic_park_pair_merged():
    """遗址公园同址族行程级同闸：大明宫遗址公园 vs 大明宫旅游景区
    （跨园区 ~3km < 同馆档 10km）在 VisitItem 层也并。"""
    from app.services.agent.plan import _same_visit
    from app.services.itinerary.models import GeoPoint, VisitItem

    relic = VisitItem(
        item_id="v10",
        name="大明宫国家考古遗址公园",
        category="attraction",
        city="西安",
        location=GeoPoint(lon=108.9510, lat=34.2850),
        day=3,
    )
    tourism = VisitItem(
        item_id="v20",
        name="大明宫旅游景区",
        category="attraction",
        city="西安",
        location=GeoPoint(lon=108.9430, lat=34.2680),
        day=3,
    )
    assert _same_visit(relic, tourism) is True


def test_same_visit_adjacent_distinct_stays_split():
    """反例锁死（行程级）：大雁塔 vs 陕历博 实测 ~1km 相邻但确是两站，
    新挂通道不得误并。"""
    from app.services.agent.plan import _same_visit
    from app.services.itinerary.models import GeoPoint, VisitItem

    dayanta = VisitItem(
        item_id="v11",
        name="大雁塔大唐芙蓉园景区",
        category="attraction",
        city="西安",
        location=GeoPoint(lon=108.974287901949, lat=34.21270457618454),
        day=2,
    )
    shaanxi_museum = VisitItem(
        item_id="v12",
        name="陕西历史博物馆",
        category="museum",
        city="西安",
        location=GeoPoint(lon=108.95507614635606, lat=34.22420108773571),
        day=4,
    )
    assert _same_visit(dayanta, shaanxi_museum) is False
