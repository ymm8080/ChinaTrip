"""ctrip_hours PoC unit tests — parsers, matching, reader flow (no network)."""

import asyncio

import httpx

from app.services.ctrip_hours import (
    CtripHoursReader,
    match_name,
    parse_detail_fields,
    parse_hours,
    parse_list,
    parse_rating_count,
    parse_ticket,
)

LIST_HTML = (
    "<div>\n"
    '<a href="/sight/chongqing158/s0-p1.html">下一页</a>\n'
    '<a href="https://gs.ctrip.com/html5/you/sight/Chongqing158/10377.html" '
    'title="洪崖洞民俗风貌区">洪崖洞</a>\n'
    '<a href="https://gs.ctrip.com/html5/you/sight/Chongqing158/10378.html" '
    'title="解放碑步行街">解放碑</a>\n'
    '<a href="https://gs.ctrip.com/html5/you/sight/Chongqing158.html'
    '?pageIndex=2">分页</a>\n'
    "</div>"
)

DETAIL_HTML = """
<h1>洪崖洞民俗风貌区</h1>
<div class="detail">开放时间</div>
<div>全年全天开放</div>
<div>免费开放</div>
"""


def test_parse_list_extracts_details_and_skips_pager():
    entries = parse_list(LIST_HTML)
    assert set(entries) == {"洪崖洞民俗风貌区", "解放碑步行街"}
    assert entries["洪崖洞民俗风貌区"].endswith("/sight/Chongqing158/10377.html")
    assert entries["洪崖洞民俗风貌区"].startswith("https://gs.ctrip.com")


def test_parse_hours_finds_label_value():
    assert parse_hours(DETAIL_HTML) == "全年全天开放"
    assert parse_hours("<p>没有时间字段</p>") is None


def test_match_name_substring_both_directions():
    index = {"洪崖洞民俗风貌区": "u1", "解放碑步行街": "u2"}
    assert match_name(index, "洪崖洞") == "洪崖洞民俗风貌区"
    assert match_name(index, "重庆中国三峡博物馆") is None
    assert match_name(index, "") is None


def _mock_reader(pages: dict[str, str], details: dict[str, str]):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url in pages:
            return httpx.Response(200, text=pages[url])
        if url in details:
            return httpx.Response(200, text=details[url])
        return httpx.Response(404, text="nope")

    return CtripHoursReader(timeout_seconds=2.0, transport=httpx.MockTransport(handler))


def test_reader_happy_path_index_then_detail():
    list_url = "https://gs.ctrip.com/html5/you/sight/chongqing158.html?pageIndex=1"
    reader = _mock_reader(
        pages={list_url: LIST_HTML},
        details={
            "https://gs.ctrip.com/html5/you/sight/Chongqing158/10377.html": (
                DETAIL_HTML
            )
        },
    )
    assert asyncio.run(reader.hours_for("重庆市", "洪崖洞")) == "全年全天开放"
    # second call rides the caches and must stay stable
    assert asyncio.run(reader.hours_for("重庆", "洪崖洞")) == "全年全天开放"


def test_reader_unknown_city_degrades_without_network():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request should be made for unknown cities")

    reader = CtripHoursReader(
        timeout_seconds=2.0, transport=httpx.MockTransport(handler)
    )
    assert asyncio.run(reader.hours_for("吐鲁番", "火焰山")) is None


# ---------------------------------------------------------------------
# 2026-10-20 windowed directory fetch: pages ride out _CRAWL_WINDOW at a
# time, scanned in page order; per-lookup budget (4) and per-city cap
# (12) unchanged; a per-city lock keeps concurrent lookups from
# double-crawling one city.

from app.services.ctrip_hours import _CRAWL_WINDOW  # noqa: E402

_MISS_HTML = (
    '<a href="https://gs.ctrip.com/html5/you/sight/Chongqing158/9.html" '
    'title="解放碑">解放碑</a>\n'
)


def _list_page(idx: int) -> str:
    return f"https://gs.ctrip.com/html5/you/sight/chongqing158.html?pageIndex={idx}"


def _detail(idx: int) -> str:
    return f"https://gs.ctrip.com/html5/you/sight/Chongqing158/{idx}.html"


def _pages_with_details() -> dict[str, str]:
    """List pages 1-2 plus the two detail pages LIST_HTML links to."""
    return {
        _list_page(1): LIST_HTML,
        _list_page(2): LIST_HTML,
        _detail(10377): DETAIL_HTML,  # 洪崖洞民俗风貌区
        _detail(10378): DETAIL_HTML,  # 解放碑步行街
    }


def _counting_reader(pages: dict[str, str], served: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url in pages:
            served.append(url)
            return httpx.Response(200, text=pages[url])
        return httpx.Response(404, text="nope")

    return CtripHoursReader(timeout_seconds=2.0, transport=httpx.MockTransport(handler))


def test_window_hit_on_first_page_never_fetches_beyond_window():
    served: list[str] = []
    reader = _counting_reader(_pages_with_details(), served)
    assert asyncio.run(reader.hours_for("重庆市", "洪崖洞")) is not None
    list_fetches = [u for u in served if "pageIndex=" in u]
    assert len(list_fetches) == _CRAWL_WINDOW


def test_miss_stops_at_lookup_budget_then_miss_caches():
    served: list[str] = []
    pages = {_list_page(i): f"<div>{_MISS_HTML}</div>" for i in range(1, 7)}
    reader = _counting_reader(pages, served)
    assert asyncio.run(reader.hours_for("重庆", "长江索道")) is None
    assert len([u for u in served if "pageIndex=" in u]) == 4  # budget 4
    before = len(served)
    assert asyncio.run(reader.hours_for("重庆", "长江索道")) is None
    assert len(served) == before  # miss cache → zero new requests


def test_city_cap_twelve_pages_then_exhausted():
    served: list[str] = []
    pages = {_list_page(i): f"<div>{_MISS_HTML}</div>" for i in range(1, 15)}
    reader = _counting_reader(pages, served)
    for _ in range(3):  # 3 lookups × budget 4 = the 12-page city cap
        assert asyncio.run(reader.hours_for("重庆", "长江索道")) is None
    before = len(served)
    assert asyncio.run(reader.hours_for("重庆", "长江索道")) is None
    assert len(served) == before  # exhausted → no more requests


def test_concurrent_lookups_share_one_crawl_via_city_lock():
    served: list[str] = []
    reader = _counting_reader(_pages_with_details(), served)

    async def scenario():
        return await asyncio.gather(
            reader.hours_for("重庆", "洪崖洞"),
            reader.hours_for("重庆", "解放碑"),
        )

    got = asyncio.run(scenario())
    assert got[0] is not None and got[1] is not None
    assert len([u for u in served if "pageIndex=" in u]) == _CRAWL_WINDOW


# --- 0009 扩展解析（真实页 gs.ctrip.com Chongqing158/10377 实测样本） ---


def test_parse_detail_fields_real_page_shapes():
    html = (
        "<div>4.7||/5|||1.6万条点评</div>"
        "<div>门票¥24起</div>"
        '"tagName":["亲近动物","遛娃宝藏地"]'
        "<p>⏰游玩时长：3‑4小时，园区依山而建</p>"
    )
    fields = parse_detail_fields(html)
    assert fields["rating"] == 4.7
    assert fields["rating_count"] == 16000
    assert fields["ticket_price_min"] == 24
    assert fields["ticket_price_max"] is None
    assert fields["review_tags"] == ["亲近动物", "遛娃宝藏地"]
    assert fields["suggested_duration_min"] == 210  # 3-4h 中值


def test_parse_detail_fields_degrades_cleanly():
    fields = parse_detail_fields("<html>什么都没有</html>")
    assert fields == {
        "suggested_duration_min": None,
        "rating": None,
        "rating_count": None,
        "review_tags": None,
        "ticket_price_min": None,
        "ticket_price_max": None,
    }


def test_parse_rating_count_plain_number():
    assert parse_rating_count("580条点评") == 580


def test_parse_ticket_range():
    lo, hi = parse_ticket("门票¥50-80")
    assert (lo, hi) == (50, 80)
