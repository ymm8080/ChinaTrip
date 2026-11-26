# -*- coding: utf-8 -*-
"""R41 餐厅候选「评分 × 评分数 × 距离」+ 地理簇配额 + 餐馆侧就近硬闸
（2026-11-25 用户令「附近餐厅都没有被推荐插入到餐卡。除了 RATE, GEOGRAPHIC.
还考虑一下 RATING NUMBER.」）。

取证（工作区 r41_A_code_path.md / r41_B_data_audit.md，真库只读实测）：
- 旧选择器按锚点下标序每桶 1 家、全程上限 4 → 名额全落市中心簇，后面的天零
  候选；锚点倒序传入入选 4 家全换（顺序敏感）。
- 旧并池用双向子串包含对必去去重 → 「南门涮肉(天坛店)」含必去名「天坛」被当
  重复项丢弃，离景点最近的店反而没进快照。
- 评分数只作并列键：5.0×1 条压过 4.9×648 条；无评分餐厅质量奖励反拿满分。
- preference 层默认预算不收敛 + 400 远罚把分日与落餐耦合 → geo 池 4 家进解 0
  家、池放宽到 12 家时命名餐卡 0 张（复现用户现象）。

覆盖：
1. credible_rating / quality_score：评分数单调、无评分=0、小样本满分不再胜出；
2. select_geo_rated：距离参与排序、评分数改变入选、簇轮转覆盖每一天、顺序无关；
3. 并池去重：分店名含景点名不再被误杀；必去本身是餐馆时仍按包含去重；
4. _meal_near_gate：无就近景点在场即不可选；用户点名餐馆豁免；
5. 快照侧名额随天数缩放（旧上限 4 的截断不再发生）。
"""

from __future__ import annotations

from types import SimpleNamespace

from ortools.sat.python import cp_model
from test_brief_text_input import SitesStore

from app.services.meal_geo import (
    credible_rating,
    quality_score,
    select_geo_rated,
)
from app.services.trip_solver.live import snapshot_from_request
from app.services.trip_solver.model.c09_c16 import _meal_near_gate


def _row(name, lon, lat, rating, count=None, category="food"):
    return {
        "name": name,
        "category": category,
        "location": (lon, lat),
        "rating": rating,
        "rating_count": count,
        "source_poi_id": name,
    }


class _GeoStore(SitesStore):
    """底库桩 + restaurants 表行（真库查询由只读探针覆盖，单测不打库）。"""

    def __init__(self, geo_rows=None, **kw):
        super().__init__(**kw)
        self._geo_rows = list(geo_rows or [])

    def top_pois_in_city(self, city, limit=30, *, exclude_food=True):
        return []

    def restaurant_rows_in_city(self, city):
        return list(self._geo_rows)


# ------------------------------------------------------- 评分 × 评分数（可信度）


def test_credible_rating_lets_review_count_decide():
    few = _row("小样本满分", 116.4, 39.91, 5.0, 1)
    many = _row("口碑高分", 116.4, 39.91, 4.9, 648)
    # 用户拍板：RATING NUMBER 必须作数——1 条评论的 5.0 不得压过 648 条的 4.9
    assert credible_rating(few) < credible_rating(many)
    assert quality_score(few) < quality_score(many)


def test_credible_rating_monotonic_and_bounded_by_raw_rating():
    base = _row("店", 116.4, 39.91, 4.6, 0)
    assert credible_rating(base) == 4.0  # 无评分数 → 先验（评分闸）
    prev = 0.0
    for n in (0, 1, 5, 20, 100, 1000):
        row = _row("店", 116.4, 39.91, 4.6, n)
        val = credible_rating(row)
        assert val >= prev  # 评分数越多越接近原始评分
        assert val <= 4.6  # 先验取评分闸 → 折后分永不超过原始分
        prev = val
    # 同评分数下评分越高折后越高
    assert credible_rating(_row("a", 0, 0, 4.8, 50)) > credible_rating(
        _row("b", 0, 0, 4.2, 50)
    )


def test_quality_score_no_rating_is_zero_not_full_marks():
    # 旧版无评分餐厅经 _data_priority_score 地板值落 float 域拿满质量奖励
    assert credible_rating(_row("无评分", 0, 0, None)) == 0.0
    assert quality_score(_row("无评分", 0, 0, None)) == 0
    tagged = _row("名录无评分", 0, 0, None)
    tagged["tags"] = ["curated", "intl"]
    assert quality_score(tagged) == 0
    # 有评分但无评分数：按先验 4.0 计（40），不是原始满分（50）
    assert quality_score(_row("无评分数", 0, 0, 5.0, None)) == 40


# ------------------------------------------------------------ 选择器：总分与配额


def test_selector_distance_participates_in_ranking():
    near = _row("近店", 116.4000, 39.9100, 4.5, 100)
    far = _row("远店", 116.4150, 39.9100, 4.5, 100)  # 同分同评分数，~1.28km
    picked = select_geo_rated(
        [far, near], [(116.4000, 39.9100)], per_cluster=1, limit=1
    )
    assert [r["name"] for r in picked] == ["近店"]
    both = select_geo_rated([far, near], [(116.4000, 39.9100)], per_cluster=1, limit=2)
    assert [r["name"] for r in both] == ["近店", "远店"]  # 余量也按总分排序


def test_selector_review_count_changes_pick():
    small = _row("小样本满分", 116.4010, 39.9110, 5.0, 2)
    big = _row("口碑店", 116.4010, 39.9110, 4.9, 648)
    picked = select_geo_rated(
        [small, big], [(116.4000, 39.9100)], per_cluster=1, limit=1
    )
    assert [r["name"] for r in picked] == ["口碑店"]


def _five_day_rows(anchors):
    rows = []
    for i, (lon, lat) in enumerate(anchors):
        rows.append(_row("D%d-甲" % (i + 1), lon + 0.001, lat, 4.6, 100))
        rows.append(_row("D%d-乙" % (i + 1), lon + 0.002, lat, 4.4, 50))
    return rows


def test_selector_cluster_round_robin_covers_every_day():
    # 5 个相距十几 km 的锚点（=5 个不同天的动线），每锚点旁 2 家合格餐馆
    anchors = [(116.0 + i * 0.2, 39.9) for i in range(5)]
    rows = _five_day_rows(anchors)
    picked = select_geo_rated(rows, anchors, limit=8)
    assert len(picked) == 8
    # 第一轮每簇各 1 家：5 天都有候选（旧版上限 4 按锚点序截断 → 第 5 天为零）
    assert {r["name"].split("-")[0] for r in picked[:5]} == {
        "D1",
        "D2",
        "D3",
        "D4",
        "D5",
    }
    # 旧形态对照（每簇 1 家 + 上限 4）确实只剩 4 家
    assert len(select_geo_rated(rows, anchors, per_cluster=1, limit=4)) == 4


def test_selector_fills_leftover_quota_when_few_clusters_have_supply():
    # 只有 1 个簇有货（其它天 2km 内无合格行）：簇配额是公平底线而非硬顶，
    # 剩余名额按总分补足——否则全池上限空转（实测 8 个名额只选出 4 家）。
    rows = [
        _row("一", 116.4010, 39.9100, 4.9, 500),
        _row("二", 116.4020, 39.9100, 4.7, 300),
        _row("三", 116.4015, 39.9100, 4.5, 200),
        _row("四", 116.4012, 39.9100, 4.4, 100),
    ]
    picked = select_geo_rated(rows, [(116.4000, 39.9100)], per_cluster=2, limit=4)
    assert [r["name"] for r in picked] == ["一", "二", "三", "四"]
    capped = select_geo_rated(rows, [(116.4000, 39.9100)], per_cluster=2, limit=3)
    assert [r["name"] for r in capped] == ["一", "二", "三"]


def test_selector_anchor_order_does_not_change_selected_set():
    anchors = [(116.0 + i * 0.2, 39.9) for i in range(5)]
    rows = _five_day_rows(anchors)
    # 每簇 1 家、名额正好 5（无截断无余量）：入选集合与锚点顺序无关
    # （旧版上限 4 按锚点序截断，倒序传入入选 4 家全换）
    forward = select_geo_rated(rows, anchors, per_cluster=1, limit=5)
    backward = select_geo_rated(rows, list(reversed(anchors)), per_cluster=1, limit=5)
    assert len(forward) == 5
    assert {r["name"] for r in forward} == {r["name"] for r in backward}
    # 不截断（limit 覆盖全部配额）时同样顺序无关
    all_f = select_geo_rated(rows, anchors, limit=10)
    all_b = select_geo_rated(rows, list(reversed(anchors)), limit=10)
    assert len(all_f) == 10
    assert {r["name"] for r in all_f} == {r["name"] for r in all_b}


def test_selector_same_venue_cluster_shares_quota():
    # 同一天的两个景点相距 300m（同簇）：配额 2 给午/晚两家，而不是每个
    # 锚点各 2 家把全程名额吃光
    anchors = [(116.4000, 39.9100), (116.4030, 39.9100)]
    rows = [
        _row("甲", 116.4010, 39.9100, 4.9, 500),
        _row("乙", 116.4020, 39.9100, 4.7, 300),
        _row("丙", 116.4015, 39.9100, 4.5, 200),
    ]
    picked = select_geo_rated(rows, anchors, limit=2)
    assert [r["name"] for r in picked] == ["甲", "乙"]


# ------------------------------------------------------------------ 并池去重


def test_branch_named_after_sight_is_not_deduped_away():
    store = _GeoStore(
        [_row("南门涮肉(天坛店)", 116.4120, 39.8840, 4.5, 106)],
        known={
            ("北京", "天坛"): {
                "name": "天坛",
                "city": "北京",
                "category": "temple",
                "location": (116.4128, 39.8836),
            }
        },
    )
    snap = snapshot_from_request(
        cities=["北京"],
        days=2,
        start_date="2026-12-01",
        musts=["天坛"],
        store=store,
    )
    names = {c.name for c in snap.candidates if c.category == "food"}
    # 旧版：「天坛」⊂「南门涮肉(天坛店)」→ 双向子串包含误判成必去重复项
    assert "南门涮肉(天坛店)" in names


def test_requested_restaurant_must_still_dedupes_its_branches():
    store = _GeoStore(
        [_row("南门涮肉(天坛店)", 116.4120, 39.8840, 4.5, 106)],
        known={
            ("北京", "南门涮肉"): {
                "name": "南门涮肉",
                "city": "北京",
                "category": "food",
                "location": (116.4128, 39.8836),
            }
        },
    )
    snap = snapshot_from_request(
        cities=["北京"],
        days=2,
        start_date="2026-12-01",
        musts=["南门涮肉"],
        store=store,
    )
    names = [c.name for c in snap.candidates if c.category == "food"]
    # 必去本身就是餐馆：同一家店的另一分店不重复进池（用户已点名）
    assert names == ["南门涮肉"]


def test_snapshot_geo_quota_scales_with_trip_days():
    # 6 个分散必去（各自一簇）各带 1 家餐馆：4 天行程名额 = 2×4=8，
    # 旧版全程上限 4 会截掉 2 家
    known = {}
    rows = []
    for i in range(6):
        lon = 116.0 + i * 0.2
        name = "景点%d" % (i + 1)
        known[("北京", name)] = {
            "name": name,
            "city": "北京",
            "category": "attraction",
            "location": (lon, 39.9),
        }
        rows.append(_row("餐馆%d" % (i + 1), lon + 0.001, 39.9, 4.6, 100))
    store = _GeoStore(rows, known=known)
    snap = snapshot_from_request(
        cities=["北京"],
        days=4,
        start_date="2026-12-01",
        musts=["景点%d" % (i + 1) for i in range(6)],
        store=store,
    )
    names = {c.name for c in snap.candidates if c.category == "food"}
    assert names == {"餐馆%d" % (i + 1) for i in range(6)}
    assert all(c.meal_slot == "any" for c in snap.candidates if c.category == "food")


# ------------------------------------------------------------ 就近硬闸（C-09 侧）


def _gate_model(sight_days, *, far_rid=None):
    model = cp_model.CpModel()
    sight = SimpleNamespace(
        cid="s1", category="museum", meal_slot=None, lon=116.400, lat=39.910, rid=None
    )
    near = SimpleNamespace(
        cid="f1", category="food", meal_slot="any", lon=116.401, lat=39.911, rid=None
    )
    far = SimpleNamespace(
        cid="f2", category="food", meal_slot="any", lon=117.200, lat=40.300, rid=far_rid
    )
    days = [1, 2]
    cids = ["s1", "f1", "f2"]
    presence = {
        (cid, day): model.NewBoolVar("p_%s_%d" % (cid, day))
        for cid in cids
        for day in days
    }
    bundle = SimpleNamespace(model=model, presence=presence, days=days)
    enriched = SimpleNamespace(snapshot=SimpleNamespace(candidates=[sight, near, far]))
    _meal_near_gate(bundle, enriched)
    for day in days:
        model.Add(presence[("s1", day)] == (1 if day in sight_days else 0))
    model.Maximize(
        190 * sum(presence[(cid, day)] for cid in ("f1", "f2") for day in days)
    )
    solver = cp_model.CpSolver()
    assert solver.Solve(model) == cp_model.OPTIMAL
    return solver, presence


def test_near_gate_blocks_all_days_when_sight_never_present():
    solver, presence = _gate_model(sight_days=())
    # 就近景点一天都不在场 → 近店也无处可落；远店本就全程不可选
    assert solver.Value(presence[("f1", 1)]) == 0
    assert solver.Value(presence[("f1", 2)]) == 0
    assert solver.Value(presence[("f2", 1)]) == 0
    assert solver.Value(presence[("f2", 2)]) == 0


def test_near_gate_allows_each_day_with_near_sight():
    solver, presence = _gate_model(sight_days=(1, 2))
    assert solver.Value(presence[("f1", 1)]) == 1
    assert solver.Value(presence[("f1", 2)]) == 1
    assert solver.Value(presence[("f2", 1)]) == 0


def test_user_named_restaurant_is_exempt_from_near_gate():
    # 用户点名的餐馆（rid 非空）＝显式选择，不做就近约束
    solver, presence = _gate_model(sight_days=(), far_rid="r9")
    assert solver.Value(presence[("f2", 1)]) == 1


# ------------------------------------------------------- 正餐时段窗（R41 补）


def _band_model_slot(slot: str, start_min: int) -> str:
    """与 R29 _band_model 同款模型，可选午/晚槽——正餐时段窗的判定。"""
    from app.services.trip_solver.model.c09_c16 import _r12d_hard_gates

    model = cp_model.CpModel()
    cand = SimpleNamespace(
        cid="f1", category="food", meal_slot="any", cuisine=None, rid=None
    )
    presence = {("f1", 1): model.NewBoolVar("p_f1_1")}
    start = {("f1", 1): model.NewIntVar(0, 1440, "s_f1_1")}
    meal_bound = {
        ("f1", 1, "lunch"): model.NewBoolVar("bl"),
        ("f1", 1, "dinner"): model.NewBoolVar("bd"),
    }
    bundle = SimpleNamespace(
        model=model, presence=presence, start=start, meal_bound=meal_bound, days=[1]
    )
    enriched = SimpleNamespace(snapshot=SimpleNamespace(candidates=[cand]))
    _r12d_hard_gates(bundle, enriched)
    model.Add(presence[("f1", 1)] == 1)
    model.Add(meal_bound[("f1", 1, slot)] == 1)
    mate = "dinner" if slot == "lunch" else "lunch"
    model.Add(meal_bound[("f1", 1, mate)] == 0)
    model.Add(start[("f1", 1)] == start_min)
    status = cp_model.CpSolver().Solve(model)
    return "INFEASIBLE" if status == cp_model.INFEASIBLE else "FEASIBLE"


def test_bound_lunch_cannot_land_in_breakfast_hours():
    # 旧版只卡 <15:00：09:00 的「午餐」合法（真库打磨解实测出现过）
    assert _band_model_slot("lunch", 9 * 60) == "INFEASIBLE"
    assert _band_model_slot("lunch", 10 * 60 + 30) == "INFEASIBLE"
    assert _band_model_slot("lunch", 11 * 60) == "FEASIBLE"
    assert _band_model_slot("lunch", 12 * 60 + 30) == "FEASIBLE"
    assert _band_model_slot("lunch", 15 * 60) == "INFEASIBLE"


def test_bound_dinner_cannot_land_in_afternoon_tea_hours():
    assert _band_model_slot("dinner", 15 * 60 + 30) == "INFEASIBLE"
    assert _band_model_slot("dinner", 17 * 60) == "FEASIBLE"
    assert _band_model_slot("dinner", 19 * 60 + 30) == "FEASIBLE"


# ------------------------------------------- 餐绑定打磨（钉分日的小求解，R41）


def _polish_fixture():
    from app.services.trip_solver.inputs.enrich import enrich
    from app.services.trip_solver.model.c01_c04 import build_model
    from app.services.trip_solver.model.objectives import build_objectives

    store = _GeoStore(
        [_row("近店", 116.4010, 39.9100, 4.9, 500)],
        known={
            ("北京", "故宫博物院"): {
                "name": "故宫博物院",
                "city": "北京",
                "category": "museum",
                "location": (116.3970, 39.9160),
            }
        },
    )
    snap = snapshot_from_request(
        cities=["北京"],
        days=1,
        start_date="2026-12-01",
        musts=["故宫博物院"],
        store=store,
    )
    enriched = enrich(snap)
    bundle = build_model(enriched)
    tiers = build_objectives(bundle, enriched)
    pref = next(t for t in tiers if t.name == "preference")
    cov = tiers[0]
    model = bundle.model
    if getattr(cov, "sense", "max") == "min":
        model.Minimize(cov.expression)
    else:
        model.Maximize(cov.expression)
    solver = cp_model.CpSolver()
    assert solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    return bundle, enriched, pref, solver


def test_meal_polish_binds_nearby_restaurant_with_days_pinned():
    from app.services.trip_solver.model.solve import _polish_meal_bindings

    bundle, enriched, pref, base = _polish_fixture()
    constraints_before = len(bundle.model.Proto().constraints)
    polished = _polish_meal_bindings(bundle, enriched, pref, base, None, wall_s=5.0)
    assert polished is not None, "钉分日 + incumbent 热启动下打磨必须拿得到解"
    # 打磨是局部手段：钉分日/地板约束收工即撤，后续 travel 层仍看到原模型
    assert len(bundle.model.Proto().constraints) == constraints_before
    solver, _status = polished
    bound = [key for key, lit in bundle.meal_bound.items() if solver.Value(lit) == 1]
    assert bound, "就近餐厅应被绑进餐槽（用户诉求：附近餐厅进餐卡）"
    cid, day, slot = bound[0]
    start = solver.Value(bundle.start[(cid, day)])
    if slot == "lunch":
        assert 11 * 60 <= start < 15 * 60
    else:
        assert start >= 17 * 60
    # 分日钉死：非餐候选每天是否在场与 incumbent 完全一致（词典序不被破坏）
    for (cid2, day2), lit in bundle.presence.items():
        cand = next(c for c in enriched.snapshot.candidates if c.cid == cid2)
        if (cand.category or "") == "food":
            continue
        assert solver.Value(lit) == base.Value(lit)


def test_meal_polish_returns_none_without_meal_candidates():
    from app.services.trip_solver.model.solve import _polish_meal_bindings

    enriched = SimpleNamespace(snapshot=SimpleNamespace(candidates=[]))
    assert _polish_meal_bindings(None, enriched, None, None, None, wall_s=1.0) is None


def test_selector_drops_thin_evidence_rows():
    """R41c：评分数不足（<MEAL_GEO_MIN_COUNT）的店不进自动推荐。

    用户 2026-11-25「D1 怎么会选一个只有一条评论的餐厅」：颐和园/圆明园 2km
    内只有一家 5.0×1 条的店时，宁留「自由安排」占位，也不拿一条点评充数。
    """
    from app.services.meal_geo import MEAL_GEO_MIN_COUNT

    thin = _row("一条评论满分店", 116.4005, 39.9102, 5.0, 1)
    solid = _row("口碑店", 116.4010, 39.9105, 4.4, 50)
    assert MEAL_GEO_MIN_COUNT > 1
    # 有达标店时只选达标的
    picked = select_geo_rated([thin, solid], [(116.4000, 39.9100)], per_cluster=2)
    assert [r["name"] for r in picked] == ["口碑店"]
    # 只有小样本店时宁缺
    assert select_geo_rated([thin], [(116.4000, 39.9100)]) == []
    # 披露辅助：能列出被这条闸挡下的店名
    from app.services.meal_geo import thin_evidence_nearby

    assert thin_evidence_nearby([thin, solid], [(116.4000, 39.9100)]) == [
        "一条评论满分店"
    ]


def test_rec_tagged_rows_bypass_min_count():
    """R41g（用户拍板「pois FOOD 就不要用最小样本量闸」）：人工精选行豁免。

    四季民福这类 curated 店评分数缺失/极少（人工名单=背书），被样本量闸挡掉
    等于精选永远进不了自动推荐。
    """
    from app.services.meal_geo import thin_evidence_nearby

    curated = _row("四季民福烤鸭店（故宫店）", 116.4005, 39.9102, 5.0, None)
    curated["rec_tagged"] = True
    plain_thin = _row("一条评论满分店", 116.4010, 39.9105, 5.0, 1)
    # 荐点行豁免：无评分数也能入选；普通小样本行仍被闸挡
    picked = select_geo_rated(
        [curated, plain_thin], [(116.4000, 39.9100)], per_cluster=2
    )
    assert [r["name"] for r in picked] == ["四季民福烤鸭店（故宫店）"]
    # 披露辅助同样豁免：荐点行不算「评论数不足」
    assert thin_evidence_nearby([curated, plain_thin], [(116.4000, 39.9100)]) == [
        "一条评论满分店"
    ]
