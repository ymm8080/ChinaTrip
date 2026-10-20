"""ctrip_hours PoC unit tests — parsers, matching, reader flow (no network)."""

import asyncio

import httpx

from app.services.ctrip_hours import (
    CtripHoursReader,
    match_name,
    parse_hours,
    parse_list,
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
