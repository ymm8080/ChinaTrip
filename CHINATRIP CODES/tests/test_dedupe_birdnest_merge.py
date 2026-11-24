# -*- coding: utf-8 -*-
"""鸟巢两行 DEDUP 合并口径回归（纯函数，CI 无 PG 可跑）。

锁住 2026-11-24 用户口径「幸存行必须含两行全部信息」：
全字段回填 / 数组并集 / 互补文本两存 / 名字变体全留 / 身份列不改写 /
二次执行幂等。ops 脚本不被 pytest 自动收集，故用 importlib 显式加载。
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "ops" / "dedupe_birdnest_20261124.py"
spec = importlib.util.spec_from_file_location("dedupe_birdnest_20261124", _SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# 真实库形状（2026-11-24 只读探针，只列有差异的列）
AMAP = {
    "id": "d1da799a-e982-46ae-a228-1b20082a06eb",
    "source": "amap",
    "source_poi_id": "ct_北京_15",
    "name_zh": "鸟巢(国家体育场)",
    "name_en": "Bird's Nest (National Stadium)",
    "status": "active",
    "address": "北京市朝阳区奥运村街道国家体育场南路1号",
    "address_en": "No. 1 National Stadium South Road, Olympic Park",
    "opening_hours": "今天10:00-22:00开放（21:00停止入园）",
    "opening_hours_en": "today 10:00-22:00 open (last entry 21:00)",
    "hours_source": "ctrip",
    "intro": "鸟巢即国家体育场，…2022 年冬奥会开闭幕式…",
    "intro_en": "The Bird's Nest is the National Stadium … 2022 Winter Olympics …",
    "indoor": "no",
    "rain_ok": "no",
    "origin": "cn_sync",
    "ta_rating": "4.2",
    "photos_fetched_at": datetime(2026, 11, 13, 10, 44, 48),
    "ta_fetched_at": datetime(2026, 11, 20, 8, 55, 34, 197453),
}
BAIDU = {
    "id": "11662ce5-a407-4262-9fa3-9deafbf128f0",
    "source": "baidu",
    "source_poi_id": "480b24d05abb06f29cec2b2f",
    "name_zh": "国家体育场·鸟巢",
    "name_en": "Beijing National Stadium",
    "status": "active",
    "phone": "4006002008",
    "tags": ["intl", "layla"],
    "tags_source": "layla",
    "intro": "国家体育场因独特钢结构外形被称为“鸟巢”…",
    "intro_source": "llm",
    "intro_en": "The National Stadium, nicknamed the 'Bird's Nest' …",
    "photos": [{"url": "https://p1-q.mafengwo.net/s11/aaa.jpeg", "title": ""}],
    "photos_source": "mafengwo",
    "name_aliases": ["National Stadium", "北京国家体育场"],
    "address": "北京市朝阳区国家体育场南路1号",
    "address_en": "No. 1 National Stadium South Road, Chaoyang District, Beijing",
    "ta_rating": "3.8",
    "photos_fetched_at": datetime(2026, 11, 13, 8, 0, 17),
    "ta_fetched_at": datetime(2026, 11, 20, 8, 55, 34, 24439),
}


def test_empty_keeper_fills_from_loser():
    new, action, _ = mod.merge_column("phone", None, "4006002008")
    assert (new, action) == ("4006002008", "fill")


def test_identity_columns_never_overwritten():
    for col in ("id", "source", "source_poi_id", "name_zh", "status", "location"):
        new, action, _ = mod.merge_column(col, "keeper-value", "loser-value")
        assert (new, action) == ("keeper-value", "identity"), col


def test_array_union_is_deduped():
    new, action, _ = mod.merge_column("tags", ["intl"], ["intl", "layla"])
    assert action == "union" and new == ["intl", "layla"]
    photos_k = [{"url": "a", "title": ""}]
    photos_l = [{"url": "a", "title": ""}, {"url": "b", "title": ""}]
    new2, action2, _ = mod.merge_column("photos", photos_k, photos_l)
    assert action2 == "union" and len(new2) == 2


def test_concat_preserves_both_facts_and_is_idempotent():
    merged, action, _ = mod.merge_column("intro", AMAP["intro"], BAIDU["intro"])
    assert action == "concat"
    assert "2022 年冬奥会" in merged and "独特钢结构" in merged
    # 二次执行（loser 已退役/已并入）不得重复拼接
    again, action2, _ = mod.merge_column("intro", merged, BAIDU["intro"])
    assert action2 == "keep" and again == merged


def test_timestamp_takes_newer():
    new, action, _ = mod.merge_column(
        "photos_fetched_at", AMAP["photos_fetched_at"], BAIDU["photos_fetched_at"]
    )
    assert action == "keep" and new == AMAP["photos_fetched_at"]
    older = BAIDU["ta_fetched_at"] - timedelta(days=2)
    new2, action2, _ = mod.merge_column("ta_fetched_at", older, AMAP["ta_fetched_at"])
    assert action2 == "newer" and new2 == AMAP["ta_fetched_at"]


def test_prefer_longer_single_value_text():
    new, action, _ = mod.merge_column(
        "address_en", AMAP["address_en"], BAIDU["address_en"]
    )
    assert action == "prefer_longer" and new == BAIDU["address_en"]
    # 地址中文：amap 带「奥运村街道」更详细，保留
    new2, action2, _ = mod.merge_column("address", AMAP["address"], BAIDU["address"])
    assert action2 == "keep" and new2 == AMAP["address"]


def test_scalar_conflict_keeps_keeper_without_half_parsed_value():
    new, action, _ = mod.merge_column("ta_rating", "4.2", "3.8")
    assert action == "keep_scalar" and new == "4.2"


def test_equal_values_are_not_reported_as_actions():
    for col in ("suggested_duration_min", "ta_location_id", "photos_fetch_fail"):
        new, action, _ = mod.merge_column(col, AMAP.get(col, "90"), AMAP.get(col, "90"))
        assert action == "keep" and new == AMAP.get(col, "90"), col


@pytest.mark.parametrize(
    "col",
    [
        "opening_hours",
        "hours_source",
        "indoor",
        "rain_ok",
        "origin",
        "opening_hours_en",
    ],
)
def test_keeper_only_fields_are_not_touched(col):
    new, action, _ = mod.merge_column(col, AMAP[col], None)
    assert action == "keep" and new == AMAP[col]


def test_alias_union_covers_both_rows_names_and_short_names():
    aliases = mod.build_alias_union(AMAP, BAIDU)
    for name in (
        "国家体育场·鸟巢",
        "Beijing National Stadium",
        "Bird's Nest (National Stadium)",
        "National Stadium",
        "北京国家体育场",
        "鸟巢",
        "国家体育场",
    ):
        assert name in aliases, name
    assert "鸟巢(国家体育场)" not in aliases  # keeper 自己不进别名
    assert len(aliases) == len(set(aliases))


def test_full_plan_covers_every_loser_only_field():
    """真实两行形状跑全列 plan：baidu 独有字段无一漏合并。"""
    cols = sorted(set(AMAP) | set(BAIDU))
    plan = {col: mod.merge_column(col, AMAP.get(col), BAIDU.get(col)) for col in cols}
    loser_only = (
        "phone",
        "tags",
        "tags_source",
        "intro_source",
        "photos",
        "photos_source",
        "name_aliases",
    )
    for col in loser_only:
        assert plan[col][1] in ("fill", "union"), (col, plan[col][1])
    # 两行互补事实文本都留在 keeper
    assert plan["intro"][1] == "concat" and plan["intro_en"][1] == "concat"
    # keeper 的 hours 链不被 baidu 空值覆盖
    for col in ("opening_hours", "hours_source", "indoor", "rain_ok", "origin"):
        assert plan[col][1] == "keep", col
    # 地址/英文名按信息量择一，数值冲突保留 keeper
    assert plan["address_en"][1] == "prefer_longer"
    assert plan["ta_rating"][1] == "keep_scalar"


def test_is_empty_treats_falsey_strings_and_collections():
    assert mod._is_empty(None) and mod._is_empty("") and mod._is_empty([])
    assert not mod._is_empty("no") and not mod._is_empty(0) and not mod._is_empty("0")
