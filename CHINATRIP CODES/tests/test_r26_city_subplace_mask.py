# -*- coding: utf-8 -*-
"""R26：城市解析复合地名掩蔽（2026-11-23 北京 4 天贴文「Kunming Lake」案）。

用户贴的英文行程文 Day3 写着「take a dragon boat ride across Kunming
Lake」（颐和园昆明湖）——`_parse_cities` 裸子串匹配把「Kunming」当成
目的地昆明：会话 cities=['北京','昆明']，引擎随即分城、排跨城航班与
空城日（用户实报「WHY THERE IS 昆明 flight」；实盘会话 d5972a25 的
Day2 多出昆明→北京 MU1001）。类级修复=城市名直接连着地理通名
（湖/路/街/…/Lake/Road/…）时按子地名掩蔽；行政/交通通名（市/站/机场）
与海湾（三亚湾）不掩——它们仍是城市信号。
"""

from app.services.agent.plan import (
    _match_city_token,
    _parse_cities,
    _trip_brief,
)

# ——事故原形：英文贴文里的 Kunming Lake 不是目的地昆明 ——


def test_kunming_lake_is_not_a_destination_city():
    text = (
        "Day1\nTiananmen Square → Forbidden City → Jingshan Park\n"
        "Day2\nTemple of Heaven → Shichahai → Nanluoguxiang\n"
        "Day3\nSummer Palace: take a dragon boat ride across "
        "Kunming Lake for classic imperial views.\n"
        "Day4\nWhat to eat in Beijing\n"
        "Beijing 4 days"
    )
    assert _parse_cities(text) == ["北京"]
    cities, days = _trip_brief(text)
    assert cities == ["北京"]
    assert days == 4


def test_chinese_kunminghu_is_masked():
    # 中文同族：颐和园简介「主要由万寿山和昆明湖组成」不构成昆明目的地
    assert _parse_cities("北京 4 天，颐和园主要由万寿山和昆明湖组成") == ["北京"]


def test_nanjing_road_is_not_nanjing_city():
    # 街路同族：上海的南京路步行街不构成目的地南京
    assert _parse_cities("上海 3 天，逛南京路步行街和外滩") == ["上海"]


# ——不掩面：真城市信号必须原样保留 ——


def test_genuine_kunming_still_detected():
    assert _parse_cities("昆明 5 天") == ["昆明"]
    assert _parse_cities("从北京去昆明玩 3 天") == ["北京", "昆明"]
    assert _parse_cities("Kunming 3 days") == ["昆明"]


def test_administrative_and_transport_tails_not_masked():
    # 站/市/机场是城市信号：昆明站、昆明市都还是昆明
    assert _parse_cities("从昆明站出发") == ["昆明"]
    assert _parse_cities("昆明市 2 天") == ["昆明"]


def test_bay_not_masked_sanya():
    # 海湾不掩：三亚湾是三亚的常见指称
    assert _parse_cities("住三亚湾，三亚 3 天") == ["三亚"]


def test_match_city_token_skips_subplace():
    # 答复片段认城市同样不吃子地名
    assert _match_city_token("南京路") is None
    assert _match_city_token("昆明") == "昆明"


def test_multiword_city_compound_kept():
    # 复合桥名不在掩蔽面：张家界玻璃桥仍读出张家界
    assert _parse_cities("张家界玻璃桥 2 天") == ["张家界"]
