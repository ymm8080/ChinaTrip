# -*- coding: utf-8 -*-
"""enrich_llm_web 解析器回归（2026-11-05 #2 别名轮解析器修复）。

r8 复盘：218/226 个 ValueError 是空 content 回包（web_search 吃掉输出
预算）——空串按可重试处理；非空回包实测全为纯 JSON，宽容解析做围栏/
全角标点/尾逗号兜底。
"""

import json
from types import SimpleNamespace

import pytest

import app.jobs.enrich_llm_web as J

# --- _extract_json 宽容解析 -------------------------------------------------


def test_extract_json_pure_reply():
    assert J._extract_json('{"duration_min": 120, "aliases": ["拙政园"]}') == {
        "duration_min": 120,
        "aliases": ["拙政园"],
    }


def test_extract_json_fenced_and_prose():
    fenced = '```json\n{"duration_min": 90, "aliases": []}\n```'
    assert J._extract_json(fenced) == {"duration_min": 90, "aliases": []}
    prose = '好的，结果如下：{"duration_min": 60, "aliases": ["甲"]}'
    assert J._extract_json(prose) == {"duration_min": 60, "aliases": ["甲"]}


def test_extract_json_repairs_fullwidth_and_trailing_comma():
    bad = '{"duration_min"：120，"aliases"：["甲"，"乙"，]}'
    assert J._extract_json(bad) == {"duration_min": 120, "aliases": ["甲", "乙"]}


def test_extract_json_empty_or_non_string_is_none():
    # r8 的 218 个失败形态：空 content（web_search 吃掉输出预算）
    assert J._extract_json("") is None
    assert J._extract_json("   \n  ") is None
    assert J._extract_json(None) is None
    assert J._extract_json([{"type": "text", "text": "{}"}]) is None  # 非串防御
    assert J._extract_json("[1,2]") is None  # 非 dict 不收


# --- _clean_aliases 单串拆分 ------------------------------------------------


def test_clean_aliases_accepts_delimited_string():
    # 主名过滤是全等匹配：单串拆出的「拙政园」≠「拙政园（苏州）」会保留，
    # 与列表形态口径一致（_clean_aliases 不做包含判断）。
    assert J._clean_aliases("拙政园、狮子林, 留园", "拙政园（苏州）") == [
        "拙政园",
        "狮子林",
        "留园",
    ]


def test_clean_aliases_list_and_garbage():
    assert J._clean_aliases(["甲景点", "甲景点", "http://x.cn", "ab"], "甲") == [
        "甲景点",
        "ab",
    ]
    assert J._clean_aliases(123, "甲") == []
    assert J._clean_aliases(None, "甲") == []


# --- _chat_web 空回包重试 ----------------------------------------------------


class _Resp:
    def __init__(self, content):
        self.status_code = 200
        self.headers = {}
        self._content = content

    def raise_for_status(self):
        pass

    def json(self):
        return {
            "choices": [{"message": {"content": self._content}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }


_SETTINGS = SimpleNamespace(
    glm_model_flash="test-model",
    glm_base_url="http://mock",
    glm_api_key="k",
)


def test_chat_web_retries_empty_content_and_recovers(monkeypatch):
    calls = []

    def fake_post(*a, **k):
        calls.append(1)
        return _Resp("" if len(calls) == 1 else '{"duration_min": 90, "aliases": []}')

    monkeypatch.setattr(J.httpx, "post", fake_post)
    monkeypatch.setattr(J.time, "sleep", lambda s: None)
    data, usage = J._chat_web(
        _SETTINGS, name="甲景点", city="苏州", category="sight", timeout=5
    )
    assert data == {"duration_min": 90, "aliases": []}
    assert usage["retries"] == 1  # 空回包一次重试即恢复
    assert len(calls) == 2


def test_chat_web_all_empty_raises_with_sample(monkeypatch, capsys):
    monkeypatch.setattr(J.httpx, "post", lambda *a, **k: _Resp(""))
    monkeypatch.setattr(J.time, "sleep", lambda s: None)
    with pytest.raises(ValueError, match="non-JSON reply"):
        J._chat_web(_SETTINGS, name="甲景点", city="苏州", category="sight", timeout=5)
    err = capsys.readouterr().err
    assert "parse_fail_sample" in err  # 样本落 stderr 供台账分类
    assert json.loads(err.strip().splitlines()[-1])["parse_fail_sample"] == ""
