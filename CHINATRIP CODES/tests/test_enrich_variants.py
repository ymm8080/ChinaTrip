"""enrich_baidu_map._variants 名称变体（百度/高德收割引擎共用的检索关键词）。

2026-11-04 台账样本驱动：组合名分段 + 脏变体清理。
"""

from app.jobs.enrich_baidu_map import _variants


def test_composite_name_splits_on_explicit_separators():
    got = _variants("金山·焦山·北固山风景区")
    assert "金山" in got
    assert "焦山" in got
    assert "北固山" in got


def test_prefix_strip_junk_is_cleaned():
    # 前缀剥离曾产生「－中山陵园风景区」这类带前导分隔符的脏关键词
    got = _variants("钟山风景名胜区－中山陵园风景区")
    assert "中山陵园风景区" in got
    assert all(not v.startswith(("－", "-", "·")) for v in got)


def test_no_split_on_he_character():
    # 「和」不切分：太和殿/中和殿 会被切坏
    assert _variants("太和殿") == ["太和殿"]


def test_plain_name_unchanged():
    assert _variants("颐和园") == ["颐和园"]


def test_strip_multiple_admin_prefixes():
    # 2026-11-04：旧实现只剥一层，5A 名录长名会留下「荔波县樟江景区」
    got = _variants("黔南布依族苗族自治州荔波县樟江景区")
    assert "樟江景区" in got
    assert "樟江" in got


def test_strip_stacked_suffixes():
    got = _variants("南关区世界雕塑公园景区")
    assert "世界雕塑公园" in got
    assert "世界雕塑" in got


def test_short_name_not_over_stripped():
    # 前缀剥离不得把「大理古城」这类短名剥成「古城」
    assert _variants("大理古城") == ["大理古城"]


def test_best_hit_picks_matching_candidate_not_first():
    from app.jobs.enrich_baidu_map import _best_hit

    results = [
        {"name": "其他无关景点"},
        {"name": "九寨沟景区", "detail_info": {"shop_hours": "08:00-18:00"}},
    ]
    hit = _best_hit(results, _variants("阿坝藏族羌族自治州九寨沟县九寨沟景区"))
    assert hit is not None and hit["name"] == "九寨沟景区"


def test_best_hit_returns_none_when_no_variant_matches():
    from app.jobs.enrich_baidu_map import _best_hit

    assert _best_hit([{"name": "完全不同"}], _variants("颐和园")) is None
