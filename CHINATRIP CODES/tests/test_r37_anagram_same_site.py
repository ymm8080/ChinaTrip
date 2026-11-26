# -*- coding: utf-8 -*-
"""R37 (2026-11-24): word-order-inverted variants of ONE venue collapse.

R28b 挂账①：同一实体的两个来源行「鸟巢(国家体育场)」「国家体育场·鸟巢」
互为词序倒装——norm 剥掉括号/间隔号后互不为子串，_same_site 的等值+包含
通道都不收敛 → 确认卡垫两行、池 twin 并卡层并不掉、must 合并层重复
（20+ 调用点同一缺口）。R29 数据层已把库内双行折一（ct_北京_15 keeper，
「国家体育场·鸟巢」inactive 转召回别名），贴文/LLM 变体路径仍在。

修：_same_site 增加倒装通道——归一后字符多重集相等且 ≥4 字。
"""

from app.services.agent.plan import _same_site


def test_inverted_parenthetical_variants_merge():
    # 库 keeper 名 vs 贴文/LLM 倒装变体（全/半角括号 + 间隔号）
    assert _same_site("鸟巢(国家体育场)", "国家体育场·鸟巢")
    assert _same_site("鸟巢（国家体育场）", "国家体育场·鸟巢")
    assert _same_site("国家体育场（鸟巢）", "鸟巢(国家体育场)")


def test_english_inverted_variants_merge():
    assert _same_site(
        "Bird's Nest (National Stadium)", "National Stadium (Bird's Nest)"
    )


def test_short_names_do_not_anagram_merge():
    # 2-3 字泛名/短地名：倒装通道关闭（撞车面大、无实益）
    assert not _same_site("西湖", "湖西")
    assert not _same_site("故宫", "宫故")


def test_distinct_venues_stay_distinct():
    assert not _same_site("故宫博物院", "中国美术馆")
    assert not _same_site("大足石刻", "洪崖洞")
    assert not _same_site("鸟巢(国家体育场)", "北京奥体中心鸟巢亚朵酒店")
    assert not _same_site("天坛公园", "公园天坛会")


def test_existing_channels_unchanged():
    assert _same_site("大足石刻", "重庆大足石刻景区")  # 包含
    assert _same_site("外滩", "外滩万国建筑博览群")  # 包含
    assert _same_site("大足石刻", "大足石刻")  # 等值
    assert not _same_site("", "大足石刻")  # 空边
    assert not _same_site("大足石刻", "洪崖洞")  # 异体
