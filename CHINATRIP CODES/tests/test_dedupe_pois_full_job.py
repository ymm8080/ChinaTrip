# -*- coding: utf-8 -*-
"""dedupe_pois 全字段通道的 CLI 层纯函数回归（无 PG 可跑）。

只测不碰 DB 的辅助件：跨名候选的名称信号、SQL 标识符/IN 参数构造、
以及模块可被安全 import（新通道不能拖垮旧通道的导入链）。
"""

from __future__ import annotations

from app.jobs import dedupe_pois as job


def test_longest_common_substring_cross_name_signal():
    assert (
        job._longest_common_substring("鸟巢(国家体育场)", "国家体育场·鸟巢")
        == "国家体育场"
    )
    assert (
        job._longest_common_substring("天台山风景名胜区", "天台县天台山景区")
        == "天台山"
    )
    assert job._longest_common_substring("故宫", "颐和园") == ""
    # 纯 generic 词（博物馆）长度不足 min_shared=4，不会被当同实体信号
    assert len(job._longest_common_substring("万林艺术博物馆", "桥梁博物馆")) == 3


def test_identifier_quoting_and_in_clause():
    assert job._q("pois") == '"pois"'
    assert job._q('we"ird') == '"we""ird"'
    clause, params = job._in_clause("id", ["a", "b", "c"])
    assert clause == ":id0, :id1, :id2"
    assert params == {"id0": "a", "id1": "b", "id2": "c"}


def test_csv_value_serializes_json_columns():
    assert job._csv_value(None) == ""
    assert job._csv_value(["a", "b"]) == '["a", "b"]'
    assert job._csv_value({"k": "鸟巢"}) == '{"k": "鸟巢"}'
    assert job._csv_value(4.2) == "4.2"


def test_full_channel_helpers_are_importable_without_db():
    # 新通道的 import 链不得引入副作用（建表/连库）
    assert callable(job._scan_alias_candidates)
    assert callable(job._apply_full)
    assert callable(job._rollback_batch)
    assert job._BAK_TABLE == "pois_full_dedup_bak"
