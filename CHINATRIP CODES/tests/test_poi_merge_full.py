# -*- coding: utf-8 -*-
"""全字段 POI 合并策略层回归（纯函数，CI 无 PG 可跑）。

锁住 2026-11-24 用户口径「幸存行必须含两行全部信息」的**通用版**：
schema 全 78 列覆盖闸 / 数组并集 / 互补文本多段留 / 别名默认无污染 /
1 keeper + N losers / 纯函数复核。一次性脚本 ``ops/dedupe_birdnest_20261124.py``
的口径回归仍在 ``test_dedupe_birdnest_merge.py``，两者互不替代。
"""
from __future__ import annotations

from datetime import datetime

import pytest

from app.services.poi_merge_full import (
    COLUMN_POLICIES,
    SOURCE_PRIORITY,
    FullMergePlan,
    Policy,
    UnknownPoiColumnError,
    assert_full_column_coverage,
    build_alias_union,
    choose_keeper,
    completeness,
    is_empty,
    merge_column,
    merge_rows,
    source_priority,
    union_values,
    verify_plan,
)

# 2026-11-24 information_schema 只读探针：pois 全 78 列（顺序即库顺序）
POIS_COLUMNS_78 = (
    "id", "source", "source_poi_id", "city", "name_zh", "name_en",
    "category", "status", "location", "wgs84_location", "updated_at",
    "address", "opening_hours", "hours_source", "hours_updated_at", "phone",
    "website", "rating", "rating_source", "tags", "tags_source", "intro",
    "intro_source", "photos", "photos_source", "best_visit_time",
    "best_visit_time_source", "suggested_duration_min", "origin",
    "rating_count", "review_tags", "review_tags_source", "ticket_price_min",
    "ticket_price_max", "ticket_source", "district", "business_area",
    "indoor", "rain_ok", "name_aliases", "duration_source", "review_summary",
    "review_summary_source", "reservation_required",
    "reservation_advance_days", "booking_url", "intro_en", "address_en",
    "review_tags_en", "review_summary_en", "opening_hours_en",
    "photos_fetched_at", "photos_fetch_fail", "user_family", "user_groups",
    "ta_location_id", "ta_geo_id", "ta_fetched_at", "ta_status", "ta_url",
    "ta_rating", "ta_opening_hours", "ta_suggested_duration_min",
    "ta_intro_en", "access_mode", "access_minutes", "access_gateway",
    "access_gateway_minutes", "access_note", "access_note_en",
    "access_source", "access_updated_at", "access_boarding",
    "access_boarding_lon", "access_boarding_lat", "access_service_minutes",
    "access_wait_minutes", "access_last_mile_minutes",
)

AMAP = {
    "id": "aaaaaaaa-0000-0000-0000-000000000001",
    "source": "amap",
    "source_poi_id": "ct_bj_15",
    "city": "北京",
    "name_zh": "鸟巢(国家体育场)",
    "name_en": "Bird's Nest (National Stadium)",
    "status": "active",
    "address": "北京市朝阳区奥运村街道国家体育场南路1号",
    "opening_hours": "10:00-22:00",
    "hours_source": "ctrip",
    "indoor": "no",
    "rain_ok": "no",
    "origin": "cn_sync",
    "intro": "鸟巢即国家体育场，2022 年冬奥会开闭幕式在此举行。",
    "intro_en": "The Bird's Nest hosted the 2022 Winter Olympics ceremonies.",
    "ta_rating": "4.2",
    "photos_fetched_at": datetime(2026, 11, 13, 10, 44, 48),
    "ta_fetched_at": datetime(2026, 11, 20, 8, 55, 34),
    "tags": ["intl"],
    "updated_at": datetime(2026, 11, 20, 9, 0),
}
BAIDU = {
    "id": "bbbbbbbb-0000-0000-0000-000000000002",
    "source": "baidu",
    "source_poi_id": "480b24d05abb06f29cec2b2f",
    "city": "北京",
    "name_zh": "国家体育场·鸟巢",
    "name_en": "Beijing National Stadium",
    "status": "active",
    "address": "北京市朝阳区国家体育场南路1号",
    "address_en": "No.1 National Stadium South Road, Chaoyang District, Beijing",
    "phone": "4006002008",
    "tags": ["intl", "layla"],
    "tags_source": "layla",
    "intro": "国家体育场因独特钢结构外形被称为“鸟巢”。",
    "intro_en": "The National Stadium is nicknamed for its steel structure.",
    "intro_source": "llm",
    "photos": [{"url": "https://p1.mafengwo.net/a.jpeg", "title": ""}],
    "photos_source": "mafengwo",
    "name_aliases": ["National Stadium", "北京国家体育场"],
    "ta_rating": "3.8",
    "photos_fetched_at": datetime(2026, 11, 13, 8, 0, 17),
    "updated_at": datetime(2026, 11, 19, 9, 0),
}
OSM = {
    "id": "cccccccc-0000-0000-0000-000000000003",
    "source": "osm",
    "name_zh": "国家体育场",
    "name_en": "National Stadium",
    "status": "active",
    "tags": ["landmark"],
    "intro": "2008 年北京奥运会主体育场。",
    "photos": [{"url": "https://osm.org/b.jpeg", "title": ""}],
    "ta_fetched_at": datetime(2026, 11, 22, 8, 0),
    "updated_at": datetime(2026, 11, 22, 9, 0),
}


# ---------------------------------------------------------------- 覆盖闸
def test_all_78_db_columns_have_a_policy():
    assert len(POIS_COLUMNS_78) == 78
    assert len(COLUMN_POLICIES) == 78
    assert set(COLUMN_POLICIES) == set(POIS_COLUMNS_78)
    cov = assert_full_column_coverage(POIS_COLUMNS_78)
    assert cov.column_count == 78 and cov.unknown == () and cov.stale == ()


def test_unknown_column_fails_loud_instead_of_silent_loss():
    with pytest.raises(UnknownPoiColumnError, match="new_fancy_col"):
        assert_full_column_coverage([*POIS_COLUMNS_78, "new_fancy_col"])
    with pytest.raises(UnknownPoiColumnError):
        merge_column("new_fancy_col", "x", "y")


def test_stale_policy_column_is_reported():
    cov = assert_full_column_coverage(
        [c for c in POIS_COLUMNS_78 if c != "photos_fetch_fail"]
    )
    assert cov.stale == ("photos_fetch_fail",)


def test_user_family_is_scalar_text_not_array():
    """鸟巢一次性脚本把 user_family 误列进 ARRAY_COLS，通用层必须纠正。"""
    assert COLUMN_POLICIES["user_family"] is Policy.PREFER_LONGER
    new, action, _ = merge_column(
        "user_family", "culture", "culture_and_family"
    )
    assert action == "prefer_longer" and new == "culture_and_family"


# ---------------------------------------------------------------- 单列口径
def test_identity_columns_never_overwritten():
    for col in ("id", "source", "source_poi_id", "name_zh", "status", "location"):
        new, action, _ = merge_column(col, "keeper", "loser")
        assert (new, action) == ("keeper", "identity"), col


def test_empty_keeper_fills_from_loser():
    assert merge_column("phone", None, "4006002008")[:2] == (
        "4006002008", "fill"
    )


def test_equal_values_are_not_reported_as_actions():
    for col in ("rating", "ta_rating", "photos_fetch_fail"):
        assert merge_column(col, "90", "90")[1] == "keep"


def test_array_union_is_content_deduped_and_ordered():
    new, action, _ = merge_column("tags", ["intl"], ["intl", "layla"])
    assert action == "union" and new == ["intl", "layla"]
    a = [{"url": "a"}, {"url": "b"}]
    b = [{"url": "b"}, {"url": "c"}]
    assert union_values(a, b) == [{"url": "a"}, {"url": "b"}, {"url": "c"}]


def test_concat_keeps_both_facts_and_is_idempotent():
    merged, action, _ = merge_column(
        "intro", AMAP["intro"], BAIDU["intro"], loser_source="baidu"
    )
    assert action == "concat"
    assert "2022 年冬奥会" in merged and "独特钢结构" in merged
    assert "〔baidu 行并入〕" in merged
    again, action2, _ = merge_column("intro", merged, BAIDU["intro"])
    assert action2 == "keep" and again == merged


def test_timestamp_takes_newer_and_tolerates_uncomparable():
    new, action, _ = merge_column(
        "ta_fetched_at", AMAP["ta_fetched_at"], datetime(2026, 11, 22, 8, 0)
    )
    assert action == "newer" and new == datetime(2026, 11, 22, 8, 0)
    assert merge_column("ta_fetched_at", "unknown", datetime(2026, 1, 1))[1] == "keep"


def test_prefer_longer_and_scalar_conflict():
    new, action, _ = merge_column(
        "address_en", None, BAIDU["address_en"]
    )
    assert action == "fill"
    new, action, _ = merge_column("address", AMAP["address"], BAIDU["address"])
    assert action == "keep" and new == AMAP["address"]
    new, action, _ = merge_column("ta_rating", "4.2", "3.8")
    assert action == "keep_scalar" and new == "4.2"


def test_keeper_only_fields_not_touched():
    for col in ("opening_hours", "hours_source", "indoor", "rain_ok", "origin"):
        new, action, _ = merge_column(col, AMAP[col], None)
        assert action == "keep" and new == AMAP[col]


def test_is_empty_semantics():
    assert is_empty(None) and is_empty("  ") and is_empty([]) and is_empty({})
    assert not is_empty("no") and not is_empty(0) and not is_empty("0")


# ---------------------------------------------------------------- 别名 / 选主
def test_alias_union_has_no_hardcoded_extra_by_default():
    aliases = build_alias_union(AMAP, [BAIDU])
    assert "国家体育场·鸟巢" in aliases
    assert "Beijing National Stadium" in aliases
    assert "National Stadium" in aliases
    assert "鸟巢" not in aliases, "默认不得注入任何地点专属短名"
    assert "鸟巢(国家体育场)" not in aliases  # keeper 自己不进别名
    assert len(aliases) == len(set(aliases))


def test_alias_union_accepts_explicit_extra_and_multiple_losers():
    aliases = build_alias_union(AMAP, [BAIDU, OSM], extra=("鸟巢",))
    assert "鸟巢" in aliases and "国家体育场" in aliases
    assert "2008" not in "".join(aliases)


def test_source_priority_and_choose_keeper():
    assert source_priority("amap") < source_priority("baidu")
    assert source_priority("unknown") == len(SOURCE_PRIORITY)
    picked = choose_keeper([BAIDU, AMAP])
    assert picked is AMAP, "amap 优先于未列入名单的 baidu"
    assert choose_keeper([BAIDU, AMAP], keep_id=BAIDU["id"]) is BAIDU
    with pytest.raises(KeyError):
        choose_keeper([AMAP], keep_id="not-there")


def test_completeness_counts_non_empty_columns():
    assert completeness(BAIDU, POIS_COLUMNS_78) > completeness(
        AMAP, POIS_COLUMNS_78
    ) - 5


# ---------------------------------------------------------------- 多行折合
def test_merge_rows_1_keeper_2_losers_covers_every_column():
    plan = merge_rows(POIS_COLUMNS_78, AMAP, [BAIDU, OSM])
    assert isinstance(plan, FullMergePlan)
    assert plan.column_count == 78
    assert len(plan.changed_columns) > 0
    assert plan.loser_labels == (
        "baidu:国家体育场·鸟巢", "osm:国家体育场"
    )
    # baidu 独有字段全部并入
    for col in ("phone", "tags_source", "intro_source", "photos",
                "photos_source", "address_en"):
        assert plan.columns[col].history, col
    assert plan.columns["phone"].value == "4006002008"
    assert len(plan.columns["photos"].value) == 2
    # 三段 intro 事实都留
    intro = plan.columns["intro"].value
    assert "2022 年冬奥会" in intro and "独特钢结构" in intro
    assert "2008 年北京奥运会" in intro
    # 时间戳取三者最新
    assert plan.columns["ta_fetched_at"].value == OSM["ta_fetched_at"]
    # 名字变体全留
    for name in ("国家体育场·鸟巢", "国家体育场", "北京国家体育场",
                 "Beijing National Stadium", "National Stadium"):
        assert name in plan.alias_union


def test_merge_rows_history_records_every_loser_contribution():
    plan = merge_rows(POIS_COLUMNS_78, AMAP, [BAIDU, OSM])
    intro_hist = plan.columns["intro"].history
    assert len(intro_hist) == 2
    assert {h["from"].split(":")[0] for h in intro_hist} == {"baidu", "osm"}


def test_scalar_conflict_is_ledger_only_not_a_write():
    plan = merge_rows(POIS_COLUMNS_78, AMAP, [BAIDU])
    assert "ta_rating" not in plan.changed_columns
    assert plan.columns["ta_rating"].value == "4.2"
    conflicts = [c for c in plan.conflicts if c["column"] == "ta_rating"]
    assert len(conflicts) == 1
    assert conflicts[0]["discarded_value"] == "3.8"
    assert conflicts[0]["keeper_value"] == "4.2"


def test_verify_plan_passes_on_good_result():
    plan = merge_rows(POIS_COLUMNS_78, AMAP, [BAIDU, OSM])
    after = {**AMAP, **{c: p.value for c, p in plan.columns.items()}}
    assert verify_plan(plan, after, AMAP, [BAIDU, OSM]) == []


def test_verify_plan_catches_missing_union_item_and_concat_text():
    plan = merge_rows(POIS_COLUMNS_78, AMAP, [BAIDU])
    after = {**AMAP, **{c: p.value for c, p in plan.columns.items()}}
    after["photos"] = []                      # 丢数组并集
    after["intro"] = AMAP["intro"]           # 丢 baidu 那段事实
    problems = verify_plan(plan, after, AMAP, [BAIDU])
    assert any("photos" in p for p in problems)
    assert any("intro" in p for p in problems)


def test_verify_plan_catches_lost_original_non_empty_field():
    plan = merge_rows(POIS_COLUMNS_78, AMAP, [BAIDU])
    after = {**AMAP, **{c: p.value for c, p in plan.columns.items()}}
    after["phone"] = None
    problems = verify_plan(plan, after, AMAP, [BAIDU])
    assert any("phone" in p for p in problems)


def test_merge_rows_rejects_unknown_column_before_any_merge():
    with pytest.raises(UnknownPoiColumnError):
        merge_rows([*POIS_COLUMNS_78, "brand_new_col"], AMAP, [BAIDU])
