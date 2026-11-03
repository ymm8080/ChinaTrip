"""ops/move_rest_to_pois：GLM 顺手抽酒店星级（track ②，backlog #11）。

星级词表全档 star_5…star_1（2026-11-03 用户拍板），只对 kind=hotel 生效，
tags_source 记 glm（市场口径，不冒充官方 mct）。本测试不连库：搬移点
seed_upsert 打桩，只验分类 -> 打标的接线。
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

_MOD_PATH = Path(__file__).resolve().parents[1] / "ops" / "move_rest_to_pois.py"


def _load_mod():
    spec = importlib.util.spec_from_file_location(
        "move_rest_to_pois_under_test", _MOD_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load_mod()


# ---------- prompt / 解析 ----------


def test_system_prompt_asks_star_only_for_hotel():
    assert "star" in mod._SYSTEM
    assert "1-5" in mod._SYSTEM
    assert "不确定" in mod._SYSTEM


def test_parse_accepts_star_for_hotel():
    assert mod._parse('{"kind":"hotel","subtype":"酒店","star":"5"}') == (
        "hotel",
        "",
        "酒店",
        "5",
    )
    for star in ("4", "3", "2", "1"):
        parsed = mod._parse(f'{{"kind":"hotel","subtype":"酒店","star":"{star}"}}')
        assert parsed is not None and parsed[3] == star


def test_parse_drops_star_outside_vocab_or_wrong_kind():
    # 六星/0/空串：一律留空，绝不猜
    for bad in ("6", "0", "", "五星", "unknown"):
        parsed = mod._parse(f'{{"kind":"hotel","subtype":"酒店","star":"{bad}"}}')
        assert parsed is not None and parsed[3] == ""
    # 非 hotel 即使 GLM 多嘴给 star 也不落
    assert mod._parse('{"kind":"attraction","subtype":"公园","star":"5"}')[3] == ""
    assert mod._parse('{"kind":"restaurant","cuisine":"川菜","star":"4"}')[3] == ""


def test_parse_backward_compatible_without_star_field():
    assert mod._parse('{"kind":"hotel","subtype":"酒店"}') == ("hotel", "", "酒店", "")


# ---------- amain 接线：hotel + star -> tags/star_source ----------


class _Row:
    def __init__(self, **kw):
        self.id = "r1"
        self.source_poi_id = "s1"
        self.name_zh = kw.pop("name_zh", "某某大酒店")
        self.city = "北京"
        self.review_tags = kw.pop("review_tags", None)
        self.status = "active"
        self.cuisine = None
        self.location = None
        self.wgs84_location = None


class _Query:
    def __init__(self, rows):
        # amain 的 targets 查询取 (id, name_zh, review_tags, city) 四元组
        self._rows = [(r.id, r.name_zh, r.review_tags, r.city) for r in rows]

    def filter(self, *_a, **_kw):
        return self

    def all(self):
        return self._rows


class _Session:
    def __init__(self, rows):
        self._rows = rows
        self.deleted: list = []

    def get(self, _model, _rid):
        return self._rows[0] if self._rows else None

    def query(self, *_cols):
        return _Query(self._rows)

    def delete(self, row):
        self.deleted.append(row)

    def commit(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _run(row, glm_reply, monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(
        mod, "seed_upsert", lambda *a, **kw: (calls.append(kw), "created")[1]
    )
    factories = []

    def factory():
        s = _Session([row])
        factories.append(s)
        return s

    class _Adapter:
        async def chat(self, *_a, **_kw):
            return SimpleNamespace(content=glm_reply)

    stats = asyncio.run(mod.amain(_Adapter(), factory, 1))
    return stats, calls


def test_hotel_with_star_gets_star_tag_and_glm_source(monkeypatch):
    row = _Row(review_tags=["环境好"])
    stats, calls = _run(
        row, '{"kind":"hotel","subtype":"酒店","star":"5"}', monkeypatch
    )
    assert stats["moved_to_pois_created"] == 1
    kw = calls[0]
    assert kw["category"] == "hotel"
    assert kw["tags"] == ["环境好", "star_5"]
    assert kw["tags_source"] == "glm"  # 市场口径，不冒充官方


def test_hotel_star_replaces_existing_star_tag(monkeypatch):
    # review_tags 自带旧星标时不并存（词表全档互斥）
    row = _Row(review_tags=["star_3", "环境好"])
    _stats, calls = _run(
        row, '{"kind":"hotel","subtype":"酒店","star":"4"}', monkeypatch
    )
    assert calls[0]["tags"] == ["环境好", "star_4"]


def test_hotel_without_star_keeps_review_tags_and_no_source(monkeypatch):
    row = _Row(review_tags=["环境好"])
    _stats, calls = _run(
        row, '{"kind":"hotel","subtype":"酒店","star":""}', monkeypatch
    )
    assert calls[0]["tags"] == ["环境好"]
    assert calls[0]["tags_source"] is None


def test_non_hotel_never_gets_star_tag(monkeypatch):
    row = _Row(review_tags=["环境好"])
    _stats, calls = _run(
        row, '{"kind":"attraction","subtype":"公园","star":"5"}', monkeypatch
    )
    assert calls[0]["category"] == "公园"
    assert calls[0]["tags"] == ["环境好"]
    assert calls[0]["tags_source"] is None


@pytest.mark.parametrize("star", ["1", "2", "3", "4", "5"])
def test_full_vocab_lands_for_hotel(monkeypatch, star):
    row = _Row()
    _stats, calls = _run(
        row, f'{{"kind":"hotel","subtype":"酒店","star":"{star}"}}', monkeypatch
    )
    assert calls[0]["tags"] == [f"star_{star}"]
