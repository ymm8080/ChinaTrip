# -*- coding: utf-8 -*-
"""ops/backfill_trip_item_addr 纯函数层：短名宽松命中的挑选口径。

2026-11-23 用户报「站点没地址还在」复核发现：原 contains 兜底带
`norm != wanted` 条件，西湖/朱家角这类无括号短名恒不满足 → 未命中。
补「名称互含 + 同城 + 景点类目优先 + 排除民宿噪声」挑选，本测试锁口径，
CI 无 PG 也能跑（只测纯函数，不连库）。
"""

import importlib.util
from pathlib import Path

import pytest

# ops/ 不是包，用文件路径加载模块（项目根为 cwd）
_OPS = Path(__file__).resolve().parents[1] / "ops" / "backfill_trip_item_addr.py"
_spec = importlib.util.spec_from_file_location("_backfill_addr", _OPS)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

pick_best_poi = mod.pick_best_poi
city_variants = mod.city_variants
norm_name = mod.norm_name


def _poi(name, city, cat="attraction", addr=None, hours=None, rating=0):
    return {
        "name_zh": name,
        "city": city,
        "category": cat,
        "address": addr,
        "opening_hours": hours,
        "rating": rating,
    }


# --- 短名宽松命中：这是回归的核心 ---

def test_xihu_picks_scenic_area_not_hotel_noise():
    """西湖 ⊂ 杭州西湖风景区；不得命中「西湖己度民宿」。"""
    candidates = [
        _poi("西湖己度民宿", "杭州", "hotel", "浙江省杭州市西湖区飞来峰", rating=9),
        _poi("杭州西湖风景区", "杭州", "attraction",
             "浙江省杭州市西湖区西湖街道杭州西湖风景名胜区", rating=5),
        _poi("西湖文化广场", "杭州", "attraction", "浙江省杭州市拱墅区", rating=6),
    ]
    got = pick_best_poi(candidates, "西湖", "杭州")
    assert got["name_zh"] == "杭州西湖风景区"


def test_zhujiajiao_picks_ancient_town():
    """朱家角 ⊂ 朱家角古镇（active），而非朱家角安麓酒店。"""
    candidates = [
        _poi("上海朱家角安麓酒店", "上海", "hotel", "上海市青浦区安麓酒店"),
        _poi("朱家角古镇", "上海", "attraction",
             "上海市青浦区朱家角镇朱家角古镇游客中心", rating=5),
    ]
    got = pick_best_poi(candidates, "朱家角", "上海")
    assert got["name_zh"] == "朱家角古镇"


# --- 守卫：不能回填错地址 ---

def test_rejects_wrong_city_even_if_name_overlaps():
    """瘦西湖风景区在扬州，不能给杭州的西湖回填。"""
    candidates = [_poi("瘦西湖风景区", "扬州", "attraction", "江苏扬州瘦西湖")]
    assert pick_best_poi(candidates, "西湖", "杭州") is None


def test_rejects_name_not_overlapping():
    """名字不互含，再近也不命中。"""
    candidates = [_poi("灵隐寺", "杭州", "temple", "杭州灵隐路")]
    assert pick_best_poi(candidates, "西湖", "杭州") is None


def test_rejects_candidates_without_address():
    """我们要回填的就是地址，无地址的命中行直接排除。"""
    candidates = [_poi("朱家角古镇", "上海", "attraction", None)]
    assert pick_best_poi(candidates, "朱家角", "上海") is None


def test_excludes_all_noise_categories():
    """民宿/酒店/餐/店即使互含也无资格作景点地址。"""
    candidates = [
        _poi("西湖己度民宿", "杭州", "hotel", "杭州西湖民宿"),
        _poi("西湖饭店", "杭州", "restaurant", "杭州西湖饭店"),
    ]
    assert pick_best_poi(candidates, "西湖", "杭州") is None


def test_prefers_sight_category_over_generic():
    """同为互含且有地址，景点类目排在其他类目前。"""
    candidates = [
        _poi("西湖风景区周边", "杭州", "other", "杭州西湖周边"),
        _poi("杭州西湖风景区", "杭州", "attraction", "杭州西湖风景名胜区"),
    ]
    assert pick_best_poi(candidates, "西湖", "杭州")["name_zh"] == "杭州西湖风景区"


def test_empty_candidates_returns_none():
    assert pick_best_poi([], "西湖", "杭州") is None


# --- 基础工具函数边界 ---

def test_city_variants():
    assert city_variants("杭州") == ["杭州", "杭州市"]
    assert city_variants("上海市") == ["上海", "上海市"]
    assert city_variants(None) == []


def test_norm_name_strips_parens_content_and_spaces():
    # 既定口径：剥括号（连同括号内文字一起删），与 /api/pois/detail 同款
    assert norm_name("杭州西湖（风景区）") == "杭州西湖"
    assert norm_name("朱 家 角") == "朱家角"
    assert norm_name("西湖(西湖区)") == "西湖"


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
