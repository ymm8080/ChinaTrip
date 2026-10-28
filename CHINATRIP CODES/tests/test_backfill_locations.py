# -*- coding: utf-8 -*-
"""backfill_locations 纯函数层：命中校验 / 同城相容 / source 优先档."""

from app.jobs.backfill_locations import (
    _SOURCE_RANK,
    city_compatible,
    name_overlap,
    pick_hit,
)


def _hit(name, city, loc="104.06,30.65"):
    return {"name": name, "city": city, "location": loc}


def test_pick_hit_takes_first_valid():
    hits = [
        _hit("九龙沟漂流", "四川省成都市大邑县", None),  # 无坐标跳过
        {"name": "贡院", "city": "南京市", "location": "118.79,32.05"},  # 异城拒
        _hit("九龙沟", "成都市"),  # 名称互含过
    ]
    assert pick_hit(hits, "九龙沟漂流", "成都")["name"] == "九龙沟"


def test_pick_hit_rejects_wrong_city_even_if_name_equal():
    hits = [_hit("西湖", "杭州市")]
    assert pick_hit(hits, "西湖", "兰州") is None


def test_pick_hit_accepts_empty_hit_city():
    hits = [{"name": "白云山索道", "city": "", "location": "113.3,23.1"}]
    assert pick_hit(hits, "白云山索道", "广州") is not None


def test_name_overlap_strips_punctuation_and_parens():
    assert name_overlap("洪崖洞（民俗风貌区）", "洪崖洞民俗风貌区")
    assert name_overlap("西湖", "西湖风景名胜区")  # 短侧≥2 字即互含（防异地靠城校验）
    assert not name_overlap("灵隐寺", "飞来峰景区")  # 无互含拒


def test_city_compatible_tolerates_suffix_and_prefix():
    assert city_compatible("成都", "成都市")
    assert city_compatible("成都市", "四川省成都市")
    assert not city_compatible("成都", "杭州")


def test_source_rank_orders_named_lists_first():
    assert _SOURCE_RANK["unesco"] < _SOURCE_RANK["5a"] < _SOURCE_RANK["scenic"]
    assert _SOURCE_RANK["5a"] < _SOURCE_RANK["amap"]


def test_hit_lonlat_accepts_dict_string_and_tuple():
    from app.jobs.backfill_locations import hit_lonlat

    assert hit_lonlat({"location": {"lon": 104.06, "lat": 30.65}}) == (104.06, 30.65)
    assert hit_lonlat({"location": "104.06,30.65"}) == (104.06, 30.65)
    assert hit_lonlat({"location": (104.06, 30.65)}) == (104.06, 30.65)
    assert hit_lonlat({"location": {"lng": 1, "lat": 2}}) is None  # 非约定键
    assert hit_lonlat({"location": None}) is None
