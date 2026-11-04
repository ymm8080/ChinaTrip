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
