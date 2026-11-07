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
    _substitute_dup,
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


# --- ④ 同体验替代组（2026-11-07 熊猫基地/熊猫谷拍板）------------------------
# 「已经排熊猫基地，就不要排熊猫谷了。两者是替换关系」——同一体验的不同
# 选址，基地↔谷 ~58km 不是同站但互为替代，一次行程只去一处。无地理闸：
# 相距越远越要并，与 2km 保护闸方向相反。


def _cs(name, lon, lat, city, cat="attraction"):
    return {
        "name": name,
        "category": cat,
        "city": city,
        "location": {"lon": lon, "lat": lat},
    }


def _panda_cards():
    from app.services.itinerary.models import GeoPoint, VisitItem

    base = VisitItem(
        item_id="v21",
        name="成都大熊猫繁育研究基地",
        poi_id="amap:成都:熊猫基地",
        category="attraction",
        city="成都",
        location=GeoPoint(lon=104.13953, lat=30.73945),
        day=2,
    )
    valley = VisitItem(
        item_id="v22",
        name="熊猫谷",
        poi_id="amap:成都:熊猫谷",
        category="attraction",
        city="成都",
        location=GeoPoint(lon=103.59896, lat=30.96554),
        day=3,
    )
    return base, valley


def test_substitute_panda_pair_far_apart_is_twin():
    """基地 vs 熊猫谷 ~58km：替代组无地理闸，候选层/行程层都判孪生。"""
    a = _cs("成都大熊猫繁育研究基地", 104.13953, 30.73945, "成都")
    b = _cs("熊猫谷", 103.59896, 30.96554, "成都")
    assert _substitute_dup(a["name"], b["name"], "成都", "成都") is True
    assert _cand_twin(a, b) is True
    from app.services.agent.plan import _dedupe_visit_keepers, _same_visit

    base, valley = _panda_cards()
    assert _same_visit(base, valley) is True
    keepers, dropped = _dedupe_visit_keepers([base, valley])
    assert dropped == ["熊猫谷"]  # 平手先到先得：基地是 selection 序先行者


def test_substitute_same_experience_trio():
    """谷 vs 苑（都江堰中华大熊猫苑(原熊猫乐园)）~7km 同城互斥——
    一次行程只看一次熊猫，三处任两处都不并排。"""
    a = _cs("熊猫谷", 103.59896, 30.96554, "成都")
    b = _cs("都江堰中华大熊猫苑(原熊猫乐园)", 103.59485, 30.89953, "成都")
    assert _cand_twin(a, b) is True


def test_substitute_cross_city_not_blocked():
    """异地同名不误伤：汉中熊猫谷/湘西大熊猫苑与成都基地不互斥。"""
    a = _cs("成都大熊猫繁育研究基地", 104.13953, 30.73945, "成都")
    hz = _cs("熊猫谷", 107.98339, 33.67317, "汉中")
    xx = _cs("湘西凤凰县中华大熊猫苑", 109.51465, 27.96564, "湘西")
    assert _cand_twin(a, hz) is False
    assert _cand_twin(a, xx) is False


def test_substitute_hotels_and_venues_not_hit():
    """酒店挂牌/附属场馆/研学基地/雅安熊猫古城不进替代组：词素不命中。"""
    a = _cs("成都大熊猫繁育研究基地", 104.13953, 30.73945, "成都")
    rows = [
        _cs("京元丽呈酒店(成都熊猫基地店)", 104.11522, 30.74127, "成都", cat="hotel"),
        _cs("熊猫剧院", 104.14484, 30.74649, "成都", cat="entertainment"),
        _cs("熊猫时空馆", 104.14609, 30.73139, "成都"),
        _cs("熊猫小匠研学体验基地", 103.58483, 30.85939, "成都"),
        _cs("熊猫古城景区", 102.81843, 30.36722, "雅安"),
    ]
    for r in rows:
        assert _cand_twin(a, r) is False, r["name"]


def test_dup_blocks_substitute_backfill():
    """回填守卫（晨间保底/借出日回填/干日回填三处统一口径）：行程已有
    基地，保底候选熊猫谷必须被 _dup_blocks_item 拦下，不许补成第二卡。"""
    from app.services.agent.plan import _dup_blocks_item

    base, _valley = _panda_cards()
    cand = {
        "name": "熊猫谷",
        "city": "成都",
        "source_poi_id": "amap:成都:熊猫谷",
        "category": "attraction",
        "location": {"lon": 103.59896, "lat": 30.96554},
    }
    assert _dup_blocks_item(cand, base) is True


# --- ③ 泛化品类替代组（2026-11-07 拍板「类型+距离」泛化产品逻辑） ----------


def test_generic_street_pair_same_city_is_twin():
    """宽窄巷子 vs 春熙路（~2.6km 同城）：citywalk 白名单品类互斥，
    一个行程只走一条街区。"""
    a = _cs("宽窄巷子", 104.05360, 30.66370, "成都", cat="citywalk")
    b = _cs("春熙路", 104.07820, 30.65740, "成都", cat="citywalk")
    assert (
        _substitute_dup(
            a["name"],
            b["name"],
            "成都",
            "成都",
            cat_a="citywalk",
            cat_b="citywalk",
            xy_a=(104.05360, 30.66370),
            xy_b=(104.07820, 30.65740),
        )
        is True
    )
    assert _cand_twin(a, b) is True


def test_generic_street_far_suburb_not_twin():
    """>30km 出城圈不互斥：都江堰古城（~56km）可与成都任一街区并排。"""
    a = _cs("宽窄巷子", 104.05360, 30.66370, "成都", cat="citywalk")
    djy = _cs("都江堰古城", 103.61900, 31.00400, "成都", cat="citywalk")
    assert _cand_twin(a, djy) is False


def test_generic_street_cross_city_not_blocked():
    """跨城组合（成都+重庆联程）不互斥：城闸先于距离闸。"""
    a = _cs("宽窄巷子", 104.05360, 30.66370, "成都", cat="citywalk")
    cq = _cs("洪崖洞民俗风貌区", 106.57830, 29.55820, "重庆", cat="citywalk")
    assert _cand_twin(a, cq) is False


def test_museum_not_in_street_group():
    """泛化按类型不按名：武侯祠博物馆（museum）不在街区白名单，与
    春熙路（citywalk）可并排。"""
    a = _cs("成都武侯祠博物馆", 104.04630, 30.64440, "成都", cat="museum")
    b = _cs("春熙路", 104.07820, 30.65740, "成都", cat="citywalk")
    assert _cand_twin(a, b) is False


def test_generic_missing_coords_same_city_judged():
    """候选无坐标（骨架行）：同城即判互斥（宁紧勿松）。"""
    a = {"name": "宽窄巷子", "category": "citywalk", "city": "成都"}
    b = {"name": "春熙路", "category": "citywalk", "city": "成都"}
    assert _cand_twin(a, b) is True


def test_panda_and_street_groups_not_crossed():
    """具名组（熊猫）与泛化组（街区）互不相干：熊猫谷 vs 春熙路可并排。"""
    a = _cs("熊猫谷", 103.59896, 30.96554, "成都", cat="nature")
    b = _cs("春熙路", 104.07820, 30.65740, "成都", cat="citywalk")
    assert _cand_twin(a, b) is False


# --- ⑤ 伞名无坐标降级 + 族卡孪生吸收（2026-11-07 碑林双卡案）----------------
# session be915838 day4 实录：绑定行「西安碑林博物馆」无坐标（坐标要等
# _enrich_parallel 在两道去重之后才补），「城墙·碑林历史文化景区」5A 伞标
# 当族卡——伞形闸全程哑火，双卡并排一天。拍板「先类型二选一，再按距离
# 时间聚合；聚合要把成员显示出来，不许影没」。


def _beilin_anchor() -> dict:
    return {
        "name": "城墙·碑林历史文化景区",
        "city": "西安",
        "category": "attraction",
        "location": {"lon": 108.94052490245161, "lat": 34.25687582300908},
    }


def test_umbrella_no_coords_same_city_morpheme_twin():
    """绑定博物馆行无 location：同城+词素降级判同站（双向）。"""
    from app.services.agent.plan import _umbrella_cand_dup

    m = {"name": "西安碑林博物馆", "city": "西安", "category": "museum"}
    assert _umbrella_cand_dup(_beilin_anchor(), m) is True
    assert _umbrella_cand_dup(m, _beilin_anchor()) is True


def test_umbrella_no_coords_cross_city_or_missing_city_not_twin():
    """缺城/异地不猜：降级闸不跨城放行。"""
    from app.services.agent.plan import _umbrella_cand_dup

    bj = {"name": "西安碑林博物馆", "city": "北京", "category": "museum"}
    bare = {"name": "西安碑林博物馆", "category": "museum"}
    assert _umbrella_cand_dup(_beilin_anchor(), bj) is False
    assert _umbrella_cand_dup(_beilin_anchor(), bare) is False


def test_umbrella_pair_bundle_recognition():
    """组合识别（2026-11-07 终裁「还原多卡连排成组合」）：碑林伞名对判
    同族供跨日捆绑；非伞名对不判族。吸收通道（折卡）已退役。"""
    from app.services.agent.plan import _umbrella_specs_bundle

    bound = {"name": "西安碑林博物馆", "city": "西安", "category": "museum"}
    assert _umbrella_specs_bundle(_beilin_anchor(), bound) is True
    dayanta = {
        "name": "大雁塔大唐芙蓉园景区",
        "city": "西安",
        "category": "attraction",
        "location": {"lon": 108.9640, "lat": 34.2180},
    }
    shaanxi = {"name": "陕西历史博物馆", "city": "西安", "category": "museum"}
    assert _umbrella_specs_bundle(dayanta, shaanxi) is False


def test_same_visit_umbrella_pair_not_merged():
    """行程级（2026-11-07 终裁）：博物馆卡 vs 伞形景区卡不再判同站——
    伞名 visit 去重通道已退役，两卡并存（必去标各随各卡）。"""
    from app.services.agent.plan import _dedupe_visit_keepers, _same_visit
    from app.services.itinerary.models import GeoPoint, VisitItem

    museum = VisitItem(
        item_id="vm",
        name="西安碑林博物馆",
        poi_id="m1_1c7b3030b03e",
        category="museum",
        city="西安",
        location=None,
        day=4,
    )
    fam = VisitItem(
        item_id="vf",
        name="城墙·碑林历史文化景区",
        poi_id="5a_304",
        category="attraction",
        city="西安",
        location=GeoPoint(lon=108.94052490245161, lat=34.25687582300908),
        day=4,
        must=True,
    )
    assert _same_visit(museum, fam) is False
    keepers, dropped = _dedupe_visit_keepers([museum, fam])
    assert dropped == []
    assert {k.poi_id for k in keepers} == {"m1_1c7b3030b03e", "5a_304"}


def test_dup_blocks_beilin_museum_backfill():
    """回填守卫挂伞名通道：行程已有城墙·碑林族卡，保底候选碑林博物馆
    （无坐标绑定行形态）必须被拦，不许补成第二卡。"""
    from app.services.agent.plan import _dup_blocks_item
    from app.services.itinerary.models import GeoPoint, VisitItem

    fam = VisitItem(
        item_id="vf",
        name="城墙·碑林历史文化景区",
        poi_id="5a_304",
        category="attraction",
        city="西安",
        location=GeoPoint(lon=108.94052490245161, lat=34.25687582300908),
        day=4,
    )
    cand = {
        "name": "西安碑林博物馆",
        "city": "西安",
        "source_poi_id": "m1_1c7b3030b03e",
        "category": "museum",
    }
    assert _dup_blocks_item(cand, fam) is True


# --- ⑥ 伞名近邻捆绑同日（2026-11-07 终裁「还原多卡连排成组合」）----------
# 碑林博物馆和城墙·碑林景区两卡并存、判同族半径 5km；跨日的伞名对
# 拉回同日连排（不再折卡）。


def _anchor_at(lon: float) -> dict:
    s = _beilin_anchor()
    s["location"] = {"lon": lon, "lat": 34.25687582300908}
    return s


def test_bundle_specs_coords_within_5km():
    """词素+坐标 ≤5km 判捆绑（同闸 2km 的放宽档）。"""
    from app.services.agent.plan import _umbrella_specs_bundle

    near = {
        "name": "西安碑林博物馆",
        "city": "西安",
        "category": "museum",
        "location": {"lon": 108.9550, "lat": 34.2560},  # ~1.3km
    }
    assert _umbrella_specs_bundle(_beilin_anchor(), near) is True


def test_bundle_specs_coords_beyond_5km_not_bundle():
    """>5km 同城词素对不捆绑（异地选址维持互斥原语义）。"""
    from app.services.agent.plan import _umbrella_specs_bundle

    far = {
        "name": "西安碑林博物馆",
        "city": "西安",
        "category": "museum",
        "location": {"lon": 109.0400, "lat": 34.2560},  # ~9km
    }
    assert _umbrella_specs_bundle(_beilin_anchor(), far) is False


def test_bundle_specs_no_coords_same_city_and_cross_city():
    """无坐标走同城+词素降级（与伞名闸同口径）；跨城不猜。"""
    from app.services.agent.plan import _umbrella_specs_bundle

    bound = {"name": "西安碑林博物馆", "city": "西安", "category": "museum"}
    bj = {"name": "西安碑林博物馆", "city": "北京", "category": "museum"}
    assert _umbrella_specs_bundle(_beilin_anchor(), bound) is True
    assert _umbrella_specs_bundle(_beilin_anchor(), bj) is False


def test_bundle_pulls_cross_day_pair_to_must_keeper_day():
    """跨日捆绑：必去碑林博物馆（day3，无坐标）是 keeper，城墙·碑林
    （day2）拉回 day3——两卡并存同日连排。"""
    from app.services.agent.plan import _bundle_umbrella_spec_days

    museum = {"name": "西安碑林博物馆", "city": "西安", "category": "museum", "day": 3}
    museum["must"] = True
    anchor = _beilin_anchor()
    anchor["day"] = 2
    anchor["must"] = False
    notes = _bundle_umbrella_spec_days(
        [museum, anchor], {"西安碑林博物馆": {"source_poi_id": "m1_x"}}
    )
    assert notes == ["城墙·碑林历史文化景区→西安碑林博物馆"]
    assert anchor["day"] == 3
    assert museum["day"] == 3


def test_bundle_same_day_pair_untouched():
    """同日对不动（两卡并存连排），无披露。"""
    from app.services.agent.plan import _bundle_umbrella_spec_days

    museum = {"name": "西安碑林博物馆", "city": "西安", "category": "museum", "day": 3}
    anchor = _beilin_anchor()
    anchor["day"] = 3
    notes = _bundle_umbrella_spec_days([museum, anchor], {})
    assert notes == []
    assert anchor["day"] == 3


def test_bundle_beyond_5km_days_untouched():
    """>5km 不拉日：异地选址各排各天，互斥闸原语义接管。"""
    from app.services.agent.plan import _bundle_umbrella_spec_days

    museum = {
        "name": "西安碑林博物馆",
        "city": "西安",
        "category": "museum",
        "day": 3,
        "location": {"lon": 109.0400, "lat": 34.2560},
    }
    anchor = _beilin_anchor()
    anchor["day"] = 2
    notes = _bundle_umbrella_spec_days([museum, anchor], {})
    assert notes == []
    assert museum["day"] == 3
    assert anchor["day"] == 2


def test_bundle_cross_city_days_untouched():
    """跨城词素对不捆绑（城闸先行）。"""
    from app.services.agent.plan import _bundle_umbrella_spec_days

    bj = {
        "name": "西安碑林博物馆",
        "city": "北京",
        "category": "museum",
        "day": 3,
    }
    anchor = _beilin_anchor()
    anchor["day"] = 2
    notes = _bundle_umbrella_spec_days([bj, anchor], {})
    assert notes == []
    assert bj["day"] == 3
    assert anchor["day"] == 2
