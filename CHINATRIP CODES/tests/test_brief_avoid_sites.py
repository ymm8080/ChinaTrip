"""「避开/不去 X」= 排除项，不是必去（2026-11-14 北京小众案）。"""

from app.services.agent.plan import _negated_brief_sites


def test_shared_negation_covers_both_names_in_one_clause():
    text = "想走小众路线，尽量避开故宫、长城这类人山人海的大景点，节奏慢一点"
    assert _negated_brief_sites(text, ["故宫博物院", "慕田峪长城"]) == [
        "故宫博物院",
        "慕田峪长城",
    ]


def test_positive_mention_elsewhere_keeps_the_site():
    text = "既想去故宫，又不想去长城"
    assert _negated_brief_sites(text, ["故宫博物院", "慕田峪长城"]) == ["慕田峪长城"]


def test_plain_wishlist_has_no_exclusions():
    text = "五道营胡同、国子监、白塔寺、杨梅竹斜街，穿插本地小吃"
    assert (
        _negated_brief_sites(
            text, ["五道营胡同", "孔庙和国子监博物馆", "白塔寺", "杨梅竹斜街"]
        )
        == []
    )


def test_english_avoid_phrase():
    text = "avoid the Forbidden City, we prefer hutongs"
    assert _negated_brief_sites(text, ["Forbidden City", "Temple of Heaven"]) == [
        "Forbidden City"
    ]
