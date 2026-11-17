# -*- coding: utf-8 -*-
"""ZHUJIAZUI 案（2026-11-17 用户实报）：拉丁专名容错 + 目的地城市推断 + LLM
竞品压制。

用户打「I WANT TO GO TO ZHUJIAZUI…」（城市没写）→ 旧行为：底库零命中，
引擎回「从哪个城市出发」；带了城市时 LLM 把这个拼错的词另认成「陆家嘴」
（编辑距离 2 比朱家角古镇的 4 更近）——确认卡出现陆家嘴、朱家角古镇反而
不见。用户拍板：ZHUJIAZUI 不是陆家嘴；点名的地点能唯一定城就不再问城市。
"""

import asyncio
import json

from app.services.agent.plan import (
    PlanningAgent,
    PlanSession,
    _brief_typo_rival_row,
)
from app.services.llm.base import ChatResult
from app.services.poi_details import PoiDetailStore
from app.services.poi_names import latin_typo_near, latin_typo_prefix

ZJZ_BRIEF = (
    "I WANT TO GO TO ZHUJIAZUI ON DEC.02.  LEAVE HOTEL ON 11AM, PLS ARRANGE"
)


def run(coro):
    return asyncio.run(coro)


# --- ① 容错匹配原语 --------------------------------------------------------


def test_latin_typo_prefix_anchors_shared_head():
    # zhujiazui↔zhujiajiao：共享 zhujia（6）、整体距离 4 → 命中，返回共享前缀
    assert latin_typo_prefix("zhujiazui", "zhujiajiao") == 6
    # 轻度手滑（少个 o / 换个元音）都在容错内
    assert latin_typo_prefix("zhujiajia", "zhujiajiao") == 9
    assert latin_typo_prefix("zhujiajio", "zhujiajiao") == 8
    # lujiazui 与 zhujiajiao 共享前缀 0 → 永不中（用户拍板：ZHUJIAZUI 不是陆家嘴）
    assert latin_typo_prefix("lujiazui", "zhujiajiao") is None
    assert latin_typo_prefix("zhujiazui", "lujiazui") is None
    # 前缀不够长的（shang=5）：shanghai 不会吸进 Shangqiu 一类的城
    assert latin_typo_prefix("shanghai", "shangqiu") is None
    # 太短的词不参与（the bund / bundling 这类通用词）
    assert latin_typo_prefix("bund", "bundling") is None
    # 通用英文词与拼音专名不会撞（共享前缀远不到 6）
    assert latin_typo_prefix("temple", "tiananmen") is None
    assert latin_typo_prefix("museum", "mutianyu") is None
    assert latin_typo_prefix("station", "shangqiu") is None


def test_latin_typo_near_is_for_rival_detection_only():
    # lujiazui 与 zhujiazui 距离 2 ≤ 3 → 「同一拼错词的另一映射」成立
    assert latin_typo_near("zhujiazui", "lujiazui") == 2
    # zhujiajiao 与 zhujiazui 距离 4 → 不是竞品（它就是容错命中的正主）
    assert latin_typo_near("zhujiazui", "zhujiajiao") is None
    assert latin_typo_near("bund", "lujiazui") is None


# --- ② match_text_names 第三档容错 ------------------------------------------


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self._rows


class _Session:
    def __init__(self, rows):
        self._rows = rows

    def query(self, *cols):
        return _Query(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _store_with_rows(rows) -> PoiDetailStore:
    return PoiDetailStore(session_factory=lambda: _Session(rows))


_ROWS = [
    ("朱家角古镇", "Zhujiajiao Ancient Town", ["朱家角古镇景区"], "attraction", "上海"),
    ("陆家嘴", "Lujiazui", None, "other", "上海"),
    ("外滩", "The Bund", None, "nature", "上海"),
    ("朱家峪村", "Zhujiayu Village", None, "attraction", "济南"),
    ("商丘古城", "Shangqiu Ancient City", None, "attraction", "商丘"),
]


def test_match_text_names_typo_token_hits_proper_noun():
    store = _store_with_rows(_ROWS)
    hits = store.match_text_names(None, ZJZ_BRIEF)
    # 前缀正主在前，近距竞品（陆家嘴）低分垫底一并摆出待确认；跨城
    # 近名（朱家峪村，济南）不掺和——拍板「模糊匹配结果 PROPOSE FOR
    # CONFIRMATION」。
    assert [(h["name"], h["city"]) for h in hits] == [
        ("朱家角古镇", "上海"),
        ("陆家嘴", "上海"),
    ]
    assert all(h["fuzzy_word"] == "zhujiazui" for h in hits)


def test_match_text_names_near_rival_proposed_with_prefix_winner():
    store = _store_with_rows(_ROWS)
    hits = store.match_text_names(None, "goto zhujiazui")
    # 前缀正主（朱家角古镇）排前，近距竞品（陆家嘴）一并列出待确认
    assert [h["name"] for h in hits] == ["朱家角古镇", "陆家嘴"]
    # 反向：真写 lujiazui 时只命中陆家嘴——没有前缀容错认过的词，
    # 近距档不开（朱家角古镇不会被反向吸进来）
    names = [
        h["name"]
        for h in store.match_text_names(None, "want to see lujiazui skyline")
    ]
    assert names == ["陆家嘴"]


def test_match_text_names_exact_hits_still_win_over_fuzzy():
    store = _store_with_rows(_ROWS)
    names = [h["name"] for h in store.match_text_names(None, "zhujiajiao water town")]
    assert names == ["朱家角古镇"]


# --- ③ LLM 竞品压制 --------------------------------------------------------


def test_typo_rival_detects_lujiazui_mapping():
    assert _brief_typo_rival_row(
        ZJZ_BRIEF, ["Zhujiajiao Ancient Town"], "Lujiazui"
    )
    # 名字逐字来自文本（LLM 正常转写）不是竞品
    assert not _brief_typo_rival_row(
        ZJZ_BRIEF, ["Zhujiajiao Ancient Town"], "Zhujiajiao Ancient Town"
    )
    # 多词英文名/没有英文名不参与
    assert not _brief_typo_rival_row(
        ZJZ_BRIEF, ["Zhujiajiao Ancient Town"], "Oriental Pearl TV Tower"
    )
    assert not _brief_typo_rival_row(ZJZ_BRIEF, [], "Lujiazui")
    # 底库没容错命中（文本没有近词）时也不判竞品
    assert not _brief_typo_rival_row(
        "SHANGHAI 2 DAYS, THE BUND AND YUGARDEN", ["The Bund"], "Lujiazui"
    )


# --- ④ 城市没写时按点名地点推断 ---------------------------------------------


class _CityRowsStore(PoiDetailStore):
    """match_text_names 桩：city=None 回全库行，city=X 回该城行。"""

    def __init__(self, all_rows, by_city=None, known=None):
        super().__init__()
        self.all_rows = all_rows
        self.by_city = by_city or {}
        self.known = known or {}
        self.match_calls = []

    def match_text_names(self, city, text, *, limit=8):
        self.match_calls.append((city, text))
        return list(self.all_rows if city is None else self.by_city.get(city, []))

    def candidate_by_name(self, city, name):
        return self.known.get((city, name))


def _agent(store, llm):
    return PlanningAgent(llm, amap_client=None, poi_details=store)


class _ScriptedLLM:
    name = "scripted"

    def __init__(self, replies):
        self.replies = list(replies)

    async def chat(self, messages, *, temperature=0.3, max_tokens=None):
        return ChatResult(content=self.replies.pop(0), model="scripted")


def _lujiazui_llm_reply() -> str:
    return json.dumps(
        {"sites": [{"name": "陆家嘴", "kind": "sight", "city": "上海", "day": 0}]},
        ensure_ascii=False,
    )


def test_start_infers_city_and_proposes_fuzzy_rivals():
    zjz = {
        "name": "朱家角古镇",
        "name_en": "Zhujiajiao Ancient Town",
        "city": "上海",
        "category": "attraction",
        "fuzzy_word": "zhujiazui",
    }
    ljz = {
        "name": "陆家嘴",
        "name_en": "Lujiazui",
        "city": "上海",
        "category": "other",
        "fuzzy_word": "zhujiazui",
    }
    store = _CityRowsStore(
        all_rows=[zjz],
        by_city={"上海": [zjz, ljz]},
        known={("上海", "陆家嘴"): ljz},
    )
    agent = _agent(store, _ScriptedLLM([_lujiazui_llm_reply()]))

    session = run(
        agent.start(
            device_id="d1",
            cities=[],
            days=1,
            preferences=ZJZ_BRIEF,
            brief=ZJZ_BRIEF,
            lang="en",
        )
    )

    # 城市按唯一点名地点推断，不再问「哪座城市」
    assert session.cities == ["上海"]
    assert session.brief_notes and "上海" in session.brief_notes[0]
    # 模糊候选一起上确认卡（前缀正主在前），LLM 的重复映射被压掉
    assert session.state == "site_confirm"
    assert session.pending_sites == ["朱家角古镇", "陆家嘴"]
    reply = session.history[-1].content
    assert "朱家角古镇" in reply
    assert "陆家嘴" in reply
    assert "按拼写近似" in reply


def test_infer_city_skips_when_sites_span_cities():
    store = _CityRowsStore(
        all_rows=[
            {
                "name": "朱家角古镇",
                "name_en": "Zhujiajiao Ancient Town",
                "city": "上海",
                "category": "attraction",
            },
            {
                "name": "朱家峪村",
                "name_en": "Zhujiayu Village",
                "city": "济南",
                "category": "attraction",
            },
        ]
    )
    agent = _agent(store, _ScriptedLLM([]))

    inferred = run(
        agent._infer_city_from_site_text("zhujiazui and zhujiayu village")
    )
    assert inferred is None


def test_infer_city_none_without_hits():
    agent = _agent(_CityRowsStore(all_rows=[]), _ScriptedLLM([]))
    assert run(agent._infer_city_from_site_text("2 days, museums and food")) is None
    assert run(agent._infer_city_from_site_text("")) is None
    assert (
        run(agent._infer_city_from_site_text("see https://example.com/trip"))
        is None
    )


def test_mine_brief_sites_rival_filter_uses_name_en():
    store = _CityRowsStore(
        all_rows=[],
        by_city={
            "上海": [
                {
                    "name": "朱家角古镇",
                    "name_en": "Zhujiajiao Ancient Town",
                    "city": "上海",
                    "category": "attraction",
                }
            ]
        },
        known={
            ("上海", "陆家嘴"): {
                "name": "陆家嘴",
                "city": "上海",
                "category": "other",
                "name_en": "Lujiazui",
            }
        },
    )
    agent = _agent(store, _ScriptedLLM([_lujiazui_llm_reply()]))
    session = PlanSession(
        session_id="s-typo",
        device_id="d1",
        cities=["上海"],
        days=1,
        preferences=ZJZ_BRIEF,
        brief_text=ZJZ_BRIEF,
    )

    added, notes = run(agent._mine_brief_sites(session))

    # 底库容错命中出正主；LLM 的陆家嘴是同一拼错词的竞品映射 → 不入列
    assert added == ["朱家角古镇"]
    assert notes == []
    assert session.must_visits == ["朱家角古镇"]


def test_bare_typo_word_short_brief_proposes_fuzzy_candidates():
    """短句整句就是一个拼错的拉丁词（ZHUJIAZUI）：两个候选都上
    确认卡并披露（2026-11-17 拍板「GIVE 模糊匹配结果 … PROPOSE FOR
    CONFIRMATION」）；同城其它行（外滩）不许借机混进短句。
    """
    store = _store_with_rows(_ROWS)
    agent = _agent(store, _ScriptedLLM([]))
    session = PlanSession(
        session_id="s-bare-typo",
        device_id="d1",
        cities=["上海"],
        days=1,
        preferences="ZHUJIAZUI",
        brief_text="ZHUJIAZUI",
    )

    added, notes = run(agent._mine_brief_sites(session))

    assert added == ["朱家角古镇", "陆家嘴"]
    assert any("拼写近似" in n for n in notes)
    assert session.must_visits == ["朱家角古镇", "陆家嘴"]
