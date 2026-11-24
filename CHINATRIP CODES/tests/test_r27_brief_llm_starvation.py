# -*- coding: utf-8 -*-
"""R27 贴文读点·LLM 饥饿闸根修 + 必去帽取消（用户英文 4 天贴文实报
「Temple of Heaven / Shichahai / The Palace Museum NOT RECOGNIZED」）。

事故形态：英文散文里的子点（太和殿/中和殿/圜丘——描述正文提到「Hall of
Supreme Harmony」这类殿名）与同点多源行（鸟巢两行）把 match_text_names
的 8 个命中槽占满，`len(library) < MAX_BRIEF_SITES` 的 LLM 闸因此不成立
→ LLM 通道整个被跳过，用户点名的顶级站名（天坛/什刹海/故宫博物院/
颐和园/圆明园）全部没机会进必去。

两刀：①底库命中满 MAX 不再跳过 LLM（自由文本唯一读得全的通道）；
②必去数量上限取消（2026-11-23 用户拍板「MAX_BRIEF_SITES SHOULD BE
CANCELLED. THERE IS NO POINT TO HV MUST GO CAP」——按天写的贴文
routinely 点名 10-14 处，帽 8 必静默丢点名；确认卡点选/避开仍是质量
兜底）。合并层 LLM 行在前、底库行只补差额（既有口径，锚住）。
"""

import json

from test_brief_text_input import (
    ScriptedLLM,
    SitesStore,
    _session,
    _sites_reply,
    run,
)

from app.services.agent.plan import PlanningAgent

# 真实事故的底库命中形状（:8000 同款探针实测 8 行）：子点+同点多源行
# 占满命中槽，用户点名的顶级站名一个都不在里面。
_POISON_LIBRARY = [
    {
        "name": "鸟巢(国家体育场)",
        "name_en": "Bird's Nest (National Stadium)",
        "city": "北京",
        "category": "attraction",
    },
    {
        "name": "国家体育场·鸟巢",
        "name_en": "Beijing National Stadium",
        "city": "北京",
        "category": "attraction",
    },
    {
        "name": "中和殿",
        "name_en": "Hall of Central Harmony",
        "city": "北京",
        "category": "historic",
    },
    {
        "name": "北京奥林匹克公园",
        "name_en": "Beijing Olympic Park",
        "city": "北京",
        "category": "attraction",
    },
    {
        "name": "圜丘",
        "name_en": "Circular Mound Altar",
        "city": "北京",
        "category": "historic",
    },
    {
        "name": "太和殿",
        "name_en": "Hall of Supreme Harmony",
        "city": "北京",
        "category": "historic",
    },
    {
        "name": "慕田峪长城",
        "name_en": "Mutianyu Great Wall",
        "city": "北京",
        "category": "historic",
    },
    {
        "name": "天安门广场",
        "name_en": "Tiananmen Square",
        "city": "北京",
        "category": "attraction",
    },
]


def _known_for(names, city="北京"):
    return {(city, n): {"name": n, "city": city, "category": "sight"} for n in names}


def _agent(store, llm):
    return PlanningAgent(llm, amap_client=None, poi_details=store)


def test_library_full_does_not_starve_llm():
    """底库命中满 8 不再跳过 LLM：用户点名的天坛/什刹海/故宫博物院
    必须进必去（修复前：闸 `len(library) < 8` 不成立，LLM 通道整个被
    跳过，这三处永远丢）。"""
    known = _known_for(["天坛", "什刹海", "故宫博物院"])
    store = SitesStore(rows_by_city={"北京": _POISON_LIBRARY}, known=known)
    llm = ScriptedLLM([_sites_reply("天坛", "什刹海", "故宫博物院")])
    agent = _agent(store, llm)
    session = _session()

    added, notes = run(agent._mine_brief_sites(session))

    assert llm.calls == 1
    assert notes == []
    # LLM 行在前（文本顺序），用户点名的三处全在
    assert added[:3] == ["天坛", "什刹海", "故宫博物院"]
    assert session.must_visits[:3] == ["天坛", "什刹海", "故宫博物院"]
    # 底库行补差额入列（无帽）；鸟巢双源行 R37 倒装折一只留
    # 一行（夹具序里 国家体育场·鸟巢 先到先得）
    assert added[3:] == [
        "国家体育场·鸟巢",
        "中和殿",
        "北京奥林匹克公园",
        "圜丘",
        "太和殿",
        "慕田峪长城",
        "天安门广场",
    ]
    assert sum(1 for n in added if "鸟巢" in n or "国家体育场" in n) == 1


def test_llm_rows_precede_library_rows_in_text_order():
    """合并层口径不变：LLM 读出的先后就是必去顺序，底库行只补差额。"""
    names = ["天安门广场", "故宫博物院", "景山公园", "天坛", "什刹海", "南锣鼓巷"]
    known = _known_for(names)
    store = SitesStore(rows_by_city={"北京": _POISON_LIBRARY}, known=known)
    llm = ScriptedLLM([_sites_reply(*[(n, i // 4 + 1) for i, n in enumerate(names)])])
    agent = _agent(store, llm)
    session = _session()

    added, _ = run(agent._mine_brief_sites(session))

    assert added[: len(names)] == names
    # 点名天随之进 site_days（文本日程口径，既有）：Day1-3 名、Day2-2 名
    assert session.site_days["天坛"] == 1
    assert session.site_days["什刹海"] == 2


def test_no_cap_all_named_sites_enter():
    """必去帽已取消（用户拍板）：按天写的 4 天贴文点名 13 处全数读出，
    第 13 处不再被帽砍；点名天照落。"""
    thirteen = [
        "天安门广场",
        "故宫博物院",
        "景山公园",
        "前门大街",
        "天坛",
        "什刹海",
        "南锣鼓巷",
        "慕田峪长城",
        "奥林匹克公园",
        "鸟巢",
        "颐和园",
        "圆明园",
        "北海公园",
    ]
    known = _known_for(thirteen)
    store = SitesStore(rows_by_city={"北京": []}, known=known)
    llm = ScriptedLLM(
        [_sites_reply(*[(n, i // 3 + 1) for i, n in enumerate(thirteen)])]
    )
    agent = _agent(store, llm)
    session = _session()

    added, notes = run(agent._mine_brief_sites(session))

    assert notes == []
    assert added == thirteen
    assert session.must_visits == thirteen
    assert session.site_days["颐和园"] == 4
    assert session.site_days["圆明园"] == 4
    assert session.site_days["北海公园"] == 5


def _reply_with_subsites(sites, subsites) -> str:
    return json.dumps(
        {
            "sites": [
                {"name": n, "kind": "sight", "city": "北京", "day": d} for n, d in sites
            ],
            "subsites": subsites,
        },
        ensure_ascii=False,
    )


def test_parent_present_suppresses_library_subsite_rows():
    """父节点（已点名大景点）在场：模型点名的底库内部子点行不再垫卡
    （2026-11-24 用户拍板「如果父节点出现，散文子点行不应该出现」）。"""
    known = _known_for(["天坛", "什刹海", "故宫博物院"])
    store = SitesStore(rows_by_city={"北京": _POISON_LIBRARY}, known=known)
    reply = _reply_with_subsites(
        [("天坛", 2), ("什刹海", 2), ("故宫博物院", 1)],
        ["中和殿", "圜丘", "太和殿"],
    )
    agent = _agent(store, ScriptedLLM([reply]))
    session = _session()

    added, notes = run(agent._mine_brief_sites(session))

    assert notes == []
    names = set(added)
    # LLM 行在前；三个殿/坛子点行被撤，不再垫卡
    assert added[:3] == ["天坛", "什刹海", "故宫博物院"]
    assert not ({"中和殿", "圜丘", "太和殿"} & names)
    # 非子点的底库行照旧补差；鸟巢双源行 R37 倒装折一只留一行
    assert "国家体育场·鸟巢" in names
    assert "鸟巢(国家体育场)" not in names
    assert "慕田峪长城" in names


def test_user_named_subsite_survives_via_llm_row():
    """模型/用户单独点名的子点走 LLM 行，不受底库垫行撤除影响。"""
    known = _known_for(["故宫博物院", "太和殿"])
    store = SitesStore(rows_by_city={"北京": _POISON_LIBRARY}, known=known)
    reply = _reply_with_subsites(
        [("故宫博物院", 1), ("太和殿", 1)],
        ["太和殿"],
    )
    agent = _agent(store, ScriptedLLM([reply]))
    session = _session()

    added, _ = run(agent._mine_brief_sites(session))

    assert added[:2] == ["故宫博物院", "太和殿"]


def test_missing_subsites_key_is_noop():
    """模型没回 subsites 键=零过滤（fail-open，与无 LLM 行为一致）。"""
    known = _known_for(["天坛", "什刹海", "故宫博物院"])
    store = SitesStore(rows_by_city={"北京": _POISON_LIBRARY}, known=known)
    agent = _agent(store, ScriptedLLM([_sites_reply("天坛", "什刹海", "故宫博物院")]))
    session = _session()

    added, _ = run(agent._mine_brief_sites(session))

    # 鸟巢双源行 R37 倒装折一：8 行底库只补 7 行
    assert len(added) == 3 + len(_POISON_LIBRARY) - 1


def test_subsites_outside_library_rows_ignored():
    """subsites 名单只撤底库行——不在底库命中里的名字不产生任何效果。"""
    known = _known_for(["天坛", "什刹海", "故宫博物院"])
    store = SitesStore(rows_by_city={"北京": _POISON_LIBRARY}, known=known)
    reply = _reply_with_subsites(
        [("故宫博物院", 1)],
        ["外滩", "不存在的殿"],
    )
    agent = _agent(store, ScriptedLLM([reply]))
    session = _session()

    added, _ = run(agent._mine_brief_sites(session))

    assert added[:1] == ["故宫博物院"]
    # 鸟巢双源行 R37 倒装折一：8 行底库只补 7 行
    assert len(added) == 1 + len(_POISON_LIBRARY) - 1
