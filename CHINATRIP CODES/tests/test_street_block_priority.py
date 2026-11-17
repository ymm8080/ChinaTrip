"""街区演出块选点优先于普通街区（2026-11-06 三拍）。

「街区演出 PRIORITY 大于普通街区」：同档（tier 连续段）池序内演出块
稳定提到档首，档内其余成员相对序保持——只动裁定对；跨档名录梯子
（2026-11-03 名录序拍板）不动。品类/语素锚点为库实测：长安十二时辰
主题街区=entertainment+show+tags[intl,sygic,show]→tier4；永兴坊/
磁器口街区=attraction/historic+intl/sygic/tui→tier4（同档竞争现症）；
回民街/宽窄巷子=lp→tier3（跨档，梯子照旧）。
"""

from app.services.agent.plan import (
    PlanningAgent,
    _plain_street_cand,
    _theme_block_cand,
)


def _block(name="长安十二时辰主题街区", rating=4.2, tags=("intl", "sygic", "show")):
    """街区型演出块（长安十二时辰形态；「多场」 hours 落 sights 桶）。"""
    return {
        "name": name,
        "city": "西安",
        "category": "entertainment",
        "best_visit_time": "show",
        "source": "show",
        "tags": list(tags),
        "rating": rating,
        "rating_count": 3000,
        "opening_hours": "10:00-21:00（多场）",
    }


def _street(name, rating=4.7, tags=("intl", "sygic"), cat="attraction"):
    """普通街区（永兴坊/磁器口街区形态：同 tier4 档的高分街区行）。"""
    return {
        "name": name,
        "city": "西安",
        "category": cat,
        "tags": list(tags),
        "rating": rating,
        "rating_count": 20000,
    }


def _filler(name, rating=4.5):
    """非街区族同档观光点（曲江池形态）。count 与街区统一=20000，
    让期望序只反映 rating（quality=rating×(1+log2(1+count))）。"""
    return {
        "name": name,
        "city": "西安",
        "category": "attraction",
        "tags": ["intl", "sygic"],
        "rating": rating,
        "rating_count": 20000,
    }


def _run(cands, days=1):
    return [
        it["name"]
        for it in PlanningAgent._deterministic_selection(
            cands, days, {"西安": (1, days)}
        )
    ]


# ---------- 判定谓词 ----------


def test_theme_block_predicate_caliber():
    assert _theme_block_cand(_block())
    # 名含「街区」但无演出内核的普通观光行不算（洪崖洞重逢1980街区实测）
    plain_blk_name = _filler("洪崖洞重逢1980街区", 4.4)
    assert not _theme_block_cand(plain_blk_name)
    assert not _theme_block_cand(_street("永兴坊"))


def test_plain_street_predicate_caliber():
    assert _plain_street_cand(_street("回民街"))
    assert _plain_street_cand(_street("磁器口街区", cat="historic"))
    assert _plain_street_cand(_street("宽窄巷子", tags=("lp", "intl")))
    assert not _plain_street_cand(_block())
    assert not _plain_street_cand(_filler("曲江池"))


# ---------- 选层池序 ----------


def test_same_tier_block_claims_before_street():
    """同 tier4 档：块压过高分街区——裁定对主案。"""
    names = _run([_street("永兴坊", 4.8), _block(rating=4.2), _filler("曲江池", 4.5)])
    assert names == ["长安十二时辰主题街区", "永兴坊", "曲江池"]


def test_street_keeps_order_vs_nonfamily_when_block_hoists():
    """块提到档首，街区与其余成员相对序不乱：永兴坊(4.8) 仍压 曲江池(4.5)。"""
    names = _run([_street("永兴坊", 4.8), _filler("曲江池", 4.5), _block(rating=4.2)])
    assert names == ["长安十二时辰主题街区", "永兴坊", "曲江池"]


def test_no_block_street_order_untouched():
    """无块的档零扰动：街区↔非街区仍按质量序（回归护栏）。"""
    names = _run(
        [
            _street("永兴坊", 4.8),
            _filler("曲江池", 4.5),
            _street("磁器口街区", 4.3, cat="historic"),
        ]
    )
    assert names == ["永兴坊", "曲江池", "磁器口街区"]


def test_cross_tier_ladder_untouched():
    """跨档不动：回民街 lp=国际旅行网站档 tier3 仍压 sygic tier4 块
    ——11-03 名录序拍板不破（本拍只裁定同档内）。"""
    names = _run([_street("回民街", 4.6, tags=("lp", "intl")), _block(rating=4.2)])
    assert names[0] == "回民街"
    assert names[1] == "长安十二时辰主题街区"


def test_street_catalog_band_block_first():
    """tier8 街区名录档：街源演出块（tags 街区+show→tier8）压过普通
    名录街区——01 表沉浸式演艺街区 vs 老街形态。"""
    blk = _block(
        name="某沉浸式演艺街区",
        rating=4.3,
        tags=("街区", "show"),
    )
    s1 = _street(
        "大九街旅游休闲街区", 4.6, tags=("国家级旅游休闲街区",), cat="historic"
    )
    s2 = _street("杨家坪步行街", 4.4, tags=("国家级旅游休闲街区",), cat="historic")
    names = _run([s1, blk, s2])
    assert names == ["某沉浸式演艺街区", "大九街旅游休闲街区", "杨家坪步行街"]


def test_block_displaces_lowest_street_at_pool_cap():
    """优先级的实质：池上限切片前块已前置——被挤出局的是档内最低街区，
    不是块（span=1 池上限 4）。"""
    cands = [
        _street("永兴坊", 4.9),
        _street("磁器口街区", 4.8, cat="historic"),
        _filler("曲江池", 4.7),
        _block(rating=4.6),
        _street("杨家坪步行街", 4.0, cat="historic"),
    ]
    names = _run(cands)
    assert "长安十二时辰主题街区" in names
    assert "杨家坪步行街" not in names  # 档内最低街区出局，块保位
    assert names == [
        "长安十二时辰主题街区",
        "永兴坊",
        "磁器口街区",
        "曲江池",
    ]
