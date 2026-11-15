"""trip_review_tags 正文规则抽取单测（DESIGN tag_implementation_decisions_2026-11-12 §D4）。"""

from app.services.trip_review_tags import extract_prose, extract_review_tags


def test_two_independent_reviews_required():
    """同一标签须 ≥2 条独立正文命中；单条噪声不落标。"""
    one = ["这家店适合约会，气氛很好"]
    assert extract_review_tags(one) == []
    two = ["这家店适合约会", "求婚纪念日首选，约会圣地"]
    assert extract_review_tags(two) == ["约会氛围"]


def test_multi_tag_ordering_by_votes():
    """多标签按票数降序；同票按词表序（约会氛围在词表前于家庭聚餐）。"""
    prose = [
        "适合约会的地方",                       # 约会 1
        "约会纪念日都合适",                     # 约会 2
        "带娃家庭聚餐不错",                     # 家庭 1
        "家庭聚会首选，亲子友好",               # 家庭 2
        "窗外就是外滩夜景，江景绝美",           # 江景 1
        "夜景无敌，江景位值得等",               # 江景 2
        "本地人常去的街坊店",                   # 本地 1
        "当地人从小吃到大",                     # 本地 2
    ]
    tags = extract_review_tags(prose)
    assert tags[0] in ("约会氛围", "江景夜景位")  # 票数并列 2，词表序在前
    assert set(tags) == {"约会氛围", "江景夜景位", "本地人常去", "家庭聚餐"}
    assert len(tags) == 4


def test_traditional_and_english_keywords():
    """繁体与英文关键词同一词表。"""
    prose_tw = ["建議有重要約會或者紀念日來", "很適合約會的餐廳"]
    assert extract_review_tags(prose_tw) == ["约会氛围"]
    prose_en = ["Great for business dinners with private rooms", "We booked a private room for our business meal"]
    assert extract_review_tags(prose_en) == ["商务宴请"]


def test_no_keyword_no_tag():
    assert extract_review_tags(["味道不错", "分量很足", "性价比高"]) == []
    assert extract_review_tags([]) == []
    assert extract_review_tags(None) == []


def test_extract_prose_from_html_state():
    """content JSON 节点抽取 + 转义还原 + 短串/URL 过滤。"""
    html = (
        '"content":"\\u5efa\\u8bae\\u6709\\u91cd\\u8981\\u7d04\\u6703\\u6216\\u8005\\u7d00\\u5ff5\\u65e5\\u4f86\\n"'
        ',"type":0},{"content":"人均400+坐擁外灘夜景\\n夜景美到窒息","type":0},'
        '{"content":"看图","type":0},{"content":"https://example.com/x.jpg","type":1}'
    )
    prose = extract_prose(html)
    assert any("約會" in p or "约会" in p for p in prose)
    assert any("外灘夜景" in p for p in prose)
    assert "看图" not in prose  # 过短丢弃
    assert not any(p.startswith("http") for p in prose)


def test_real_sample_shape():
    """真实探针样本形态（繁体正文 + \\n 转义）端到端。

    江景/夜景两词只出现在同一条正文里——按「独立正文条数」口径只有
    约会氛围达 2 票，江景夜景位 1 票不落（防单条噪声的设计初衷）。
    """
    prose = [
        "服務生都超級專業貼心\\n雖然人均小貴\\n但絕對值得這個價格!\\n建議有重要約會或者紀念日來",
        "很適合約會的餐廳，環境安靜",
        "雲端米其林！人均400+坐擁陸家嘴外灘絕美夜景",
    ]
    assert extract_review_tags(prose) == ["约会氛围"]
