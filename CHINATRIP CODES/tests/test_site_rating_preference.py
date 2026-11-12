"""近距评分择优/择近（2026-11-12 用户拍板）。

「选 SITE 应该看评分的。如果距离在 8 公里内选评分高的。评分正在
填入」+「8 公里内，评价 RATE 差据小于 0.3 时选择近的点」：

- 同档（tier 连续段）内、距离 ≤8km 的一对一比较：评分差 ≥0.3 取高分
  者（覆盖 count 加权质量分打不过原始评分的场景）；一空一有的回填
  过渡期取有分者。
- 差 <0.3（含双方无评分）取离城心锚（_urban_medoid）近者。
- 跨档名录梯子不动（2026-11-03 名录序拍板）；手建/偏好件不参比。
- 距离 >8km 完全不扰动。

坐标为西安城区虚构点位（城心 ~108.94,34.34），只作距离几何锚。
"""

from app.services.agent.plan import (
    PlanningAgent,
    _rating_near_priority,
)


def _cand(name, rating, lon, lat, count=20000, tags=("intl", "sygic")):
    """同档（tier4=sygic 图商标）观光点，坐标 dict 形态（库读侧形态）。"""
    return {
        "name": name,
        "city": "西安",
        "category": "attraction",
        "tags": list(tags),
        "rating": rating,
        "rating_count": count,
        "location": {"lon": lon, "lat": lat},
    }


def _run(cands, days=2):
    return [
        it["name"]
        for it in PlanningAgent._deterministic_selection(
            cands, days, {"西安": (1, days)}
        )
    ]


# ---------- 单元：成对扫描 ----------


def _pair(a, b):
    return _rating_near_priority([(0, a), (1, b)])


def test_near_higher_rating_wins_over_count_weighted_quality():
    """<8km：4.8/count-0 胜 4.2/count-10000——质量分(count 加权)原本
    把 4.2 顶前，原始评分差 0.6 ≥0.3，高分者提前排。"""
    a = _cand("甲", 4.2, 108.94, 34.34, count=10000)
    b = _cand("乙", 4.8, 108.945, 34.345, count=0)
    out = _pair(a, b)
    assert [p[1]["name"] for p in out] == ["乙", "甲"]


def test_tie_band_picks_closer_to_core():
    """差 <0.3：4.5 的近城心者胜 4.6 的远者——平差取近（用户拍板）。
    五候选：锚+两伴成 3 票簇（medoid 无平局）=城心点；A/B 对在其 8km
    圈内但 B 更贴锚。"""
    core = _cand("锚", 4.0, 108.90, 34.30, count=100)
    mate1 = _cand("锚伴1", 4.0, 108.901, 34.301, count=100)
    mate2 = _cand("锚伴2", 4.0, 108.899, 34.302, count=100)
    a = _cand("远A", 4.6, 109.10, 34.45, count=100)  # 距锚 ~24.7km
    b = _cand("近B", 4.5, 109.09, 34.44, count=100)  # 距锚 ~23.3km，距A ~1.4km
    out = _rating_near_priority([(0, a), (1, b), (2, core), (3, mate1), (4, mate2)])
    names = [p[1]["name"] for p in out]
    # A/B 对：|4.5-4.6|<0.3 且 B 更贴锚 → B 提前；锚族与 A/B 距 >8km 不动。
    assert names.index("近B") < names.index("远A")


def test_beyond_8km_untouched():
    """>8km：质量序原样（4.8/count-0 仍排 4.2/count-10000 后）。"""
    a = _cand("甲", 4.2, 108.90, 34.30, count=10000)
    b = _cand("乙", 4.8, 109.20, 34.50, count=0)  # ~35km
    out = _pair(a, b)
    assert [p[1]["name"] for p in out] == ["甲", "乙"]


def test_both_none_rating_proximity_decides_no_crash():
    """双方无评分（回填中）：按 0 计差=0<0.3，近锚者胜，不崩。"""
    a = _cand("甲", None, 108.90, 34.30, count=0)
    b = _cand("乙", None, 108.905, 34.301, count=0)  # 更近锚对（medoid=甲）
    out = _pair(a, b)
    # medoid=甲（先出现者），乙不比甲更贴锚 → 原序保持。
    assert [p[1]["name"] for p in out] == ["甲", "乙"]


def test_one_none_rating_gets_promoted():
    """一空一有：取有分者（回填过渡期不让无分行吃近距红利）。"""
    a = _cand("甲", None, 108.94, 34.34, count=0)
    b = _cand("乙", 4.5, 108.945, 34.345, count=100)
    out = _pair(a, b)
    assert [p[1]["name"] for p in out] == ["乙", "甲"]


def test_cross_tier_run_untouched():
    """跨档：各档独立连续段，档间不比较（名录梯子不动）——后档高分行
    哪怕 <8km 且差 ≥0.3 也不越档提前。输入按档序（tier3 前 tier4 后），
    同真实调用方（_deterministic_selection 先按 tier 排序再过本趟）。"""
    t3 = _cand("名录档", 4.2, 108.94, 34.34, count=0, tags=("lp", "intl"))
    t4 = _cand("图商档", 4.8, 108.945, 34.345, count=10000)
    out = _rating_near_priority([(0, t3), (1, t4)])
    assert [p[1]["name"] for p in out] == ["名录档", "图商档"]


def test_created_lane_never_demoted():
    """手建卡（_created_lane）不做排前比较对象，不被降级。"""
    created = _cand("手建", 4.0, 108.94, 34.34, count=0)
    created["_created_lane"] = True
    b = _cand("高分", 4.9, 108.945, 34.345, count=100)
    out = _pair(created, b)
    assert [p[1]["name"] for p in out] == ["手建", "高分"]
    # 手建件也不借本趟插队：高位件在前时维持。
    out2 = _rating_near_priority([(0, b), (1, created)])
    assert [p[1]["name"] for p in out2] == ["高分", "手建"]


def test_baidu_rating_same_scale_discount():
    """百度源 ×0.9 与 _quality 同口径：4.55(baidu)=4.095 有效分，
    与高德的 4.2 差 0.105 <0.3 → 落平差带，不触发高分提前。"""
    a = _cand("高德", 4.2, 108.94, 34.34, count=100)
    b = _cand("百度", 4.55, 108.945, 34.345, count=100)
    b["rating_source"] = "baidu"
    out = _pair(a, b)
    # 平差带比距锚：medoid 双点平局取先出现者（高德），百度点不更
    # 近 → 原序保持。
    assert [p[1]["name"] for p in out] == ["高德", "百度"]


# ---------- 集成：选层全链 ----------


def test_selection_layer_near_rating_promotion():
    """_deterministic_selection 全链：质量分压前的低分高count行被
    <8km 内的高分行（差 ≥0.3）反超。"""
    low_rating_hot = _cand("低分热门", 4.2, 108.94, 34.34, count=100000)
    high_rating_quiet = _cand("高分冷门", 4.8, 108.945, 34.345, count=0)
    names = _run([low_rating_hot, high_rating_quiet])
    assert names[0] == "高分冷门"


def test_selection_layer_tie_band_proximity():
    """全链平差带：4.5 近城心者反超 4.6 远者（池序层生效）。"""
    cluster = [
        _cand("锚", 4.0, 108.90, 34.30, count=100),
        _cand("锚伴1", 4.0, 108.901, 34.301, count=100),
        _cand("锚伴2", 4.0, 108.899, 34.302, count=100),
    ]
    far_high = _cand("远A", 4.6, 109.10, 34.45, count=100)
    near_low = _cand("近B", 4.5, 109.09, 34.44, count=100)
    names = _run(cluster + [far_high, near_low])
    assert names.index("近B") < names.index("远A")
