# -*- coding: utf-8 -*-
"""R22 行程骨架天数（2026-11-23「4 天行程贴文被认成 1 天」案）。

贴进来的整份行程自带 Day1..DayN / 第1天..第N天 骨架：天数=最大骨架号，
标记本身不是天数陈述；裸整数兜底只认「整句就是一个数」的短答。
区间第二端点裸日号（「12月10日到13号」「Dec 10 to 13」）按首末跨度算天数。
"""

from test_comment_intake_gate import _GateStore
from test_plan_api import client_for, start

from app.api.plan import _text_date_span_days
from app.services.agent.plan import PlanningAgent, _parse_days

_PASTE_EN = (
    "Day1\nTiananmen Square, Forbidden City, Jingshan Park\n"
    "Day2\nTemple of Heaven\nDay3\nSummer Palace\nDay4\nGreat Wall"
)


def test_parse_days_marker_skeleton_english():
    assert _parse_days(_PASTE_EN) == 4


def test_parse_days_marker_skeleton_chinese():
    assert _parse_days("第1天 故宫\n第2天 长城\n第3天 颐和园\n第4天 天坛") == 4


def test_parse_days_single_marker_is_not_days():
    assert _parse_days("把第2天的行程换一下") is None
    assert _parse_days("Day1\nTiananmen Square, Forbidden City") is None


def test_parse_days_bare_int_whole_answer_only():
    assert _parse_days("5") == 5
    # 晚数不折天数（与「三晚」同口径，交 LLM）。
    assert _parse_days("住3晚") is None
    assert _parse_days("visit for 2 hours") is None


def test_parse_days_still_reads_plain_counts():
    assert _parse_days("北京 3 天") == 3
    assert _parse_days("三日游") == 3


def test_span_days_bare_second_endpoint_cn():
    assert _text_date_span_days("12月10日到13号") == 4


def test_span_days_bare_second_endpoint_en():
    assert _text_date_span_days("Dec 10 to 13") == 4


def test_span_days_full_range_regression():
    assert _text_date_span_days("11月30号到12月7号") == 8
    assert _text_date_span_days("Nov 30 to Dec 7") == 8


def test_start_marker_paste_with_request_date_no_intake():
    # 贴 Day1..Day4 行程 + 请求自带出发日期（H5 常规携带）
    # → 不弹行前卡（修前 text_days 被 Day1 读成 1、又缺日期→弹）。
    agent = PlanningAgent(None, amap_client=None, poi_details=_GateStore())
    resp = start(
        client_for(agent),
        {"brief": _PASTE_EN, "start_date": "2026-11-30"},
    )
    body = resp.json()
    assert body["state"] != "intake"


def test_start_marker_paste_with_card_span_no_confirm():
    # 贴 Day1..Day4 行程 + 卡起止 11-30→12-03（跨度 4）→ 文字侧天数也是 4：
    # 不再出「文字 1 天 vs 卡 4 天」差异确认（实锤 14ms 弹卡循环）。
    agent = PlanningAgent(None, amap_client=None, poi_details=_GateStore())
    resp = start(
        client_for(agent),
        {
            "brief": _PASTE_EN,
            "start_date": "2026-11-30",
            "arrival_date": "2026-11-30",
            "departure_date": "2026-12-03",
        },
    )
    body = resp.json()
    assert body["state"] not in ("intake", "confirm_route")
