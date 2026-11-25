# -*- coding: utf-8 -*-
"""R39 (2026-11-25): one transit-leg format, and legs at the hotel boundary.

User reports (live Day1: 酒店 → 颐和园 → 听鹂馆):
1. Three different on-screen leg shapes for the same kind of transfer (card
   footer text / timeline bridge card / structured "打车 … → 下一站" row).
   Every transfer must render as ONE row carrying the same fields — that
   needs the bridge card to carry the footer's leg fields (distance / mode /
   minutes / fare), which it never had.
2. "DAY1 FROM HOTEL TO SITE 1 颐和园, NO TRANSPORTATION LEG" — the morning
   hotel card is a placeholder without coordinates, so ``leg_pairs`` skipped
   it and the hotel boundary never produced a leg at all.
"""

from __future__ import annotations

from datetime import time

import pytest

from app.services.itinerary.legs import annotate_legs, leg_pairs
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    VisitItem,
)
from app.services.trip_solver.assembly.bridges import attach_gap_bridges

# 颐和园 / 天坛 coordinates (straight-line distance from the 北京 anchor
# 39.9042,116.4074 is ~13-14 km and ~4-5 km respectively).
SUMMER_PALACE = (116.27, 39.99)
TEMPLE_OF_HEAVEN = (116.41, 39.88)
REMOTE = (116.57, 40.43)  # 慕田峪一带


def _v(item_id, name, start, end, *, cat="attraction", city="北京", loc=None, **kw):
    dur = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
    return VisitItem(
        item_id=item_id,
        name=name,
        city=city,
        day=1,
        category=cat,
        duration_minutes=kw.pop("dur", dur),
        location=GeoPoint(lon=loc[0], lat=loc[1]) if loc else None,
        start_time=start,
        end_time=end,
        **kw,
    )


def _morning(start=time(8, 30), city="北京", loc=None):
    return _v(
        "hotel-morning-d1",
        "从酒店出发",
        start,
        start,
        cat="hotel",
        city=city,
        loc=loc,
        dur=0,
    )


def _plan(items):
    return ItineraryPlan(
        itinerary_id="t39",
        cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=items)],
        assumptions=[],
    )


def _ids(plan):
    return [(a.item_id, b.item_id) for a, b, _km in leg_pairs(plan)]


# ---------------------------------------------------------------------------
# 2) hotel boundary: morning card departs, evening card stays transparent
# ---------------------------------------------------------------------------


def test_hotel_morning_becomes_departure_card_with_city_anchor():
    plan = _plan(
        [
            _morning(),
            _v("s1", "颐和园", time(9, 20), time(11, 55), loc=SUMMER_PALACE),
        ]
    )
    assert _ids(plan) == [("hotel-morning-d1", "s1")]
    annotate_legs(plan)
    leg = plan.days[0].items[0]
    assert leg.next_leg_mode == "taxi"
    # 出发点=北京城市锚（39.9042, 116.4074）——直线距离按同一公式算，不靠手算常数
    from app.services.itinerary.rules import haversine_km

    expect_km = haversine_km(
        GeoPoint(lon=116.4074, lat=39.9042),
        GeoPoint(lon=SUMMER_PALACE[0], lat=SUMMER_PALACE[1]),
    )
    assert leg.distance_to_next_km == pytest.approx(expect_km, abs=0.01)
    assert expect_km > 10  # 确实是从市中心到颐和园的量级，不是同址
    assert isinstance(leg.next_leg_minutes, int) and leg.next_leg_minutes > 0
    assert isinstance(leg.next_leg_cost_cny, (int, float))
    assert leg.next_walk_minutes is not None  # H5 footer gate


def test_real_hotel_coordinates_win_over_city_anchor():
    far = (116.85, 40.05)  # a real hotel far out east
    plan = _plan(
        [
            _morning(loc=far),
            _v("s1", "颐和园", time(9, 20), time(11, 55), loc=SUMMER_PALACE),
        ]
    )
    ((_a, _b, km),) = leg_pairs(plan)
    assert km == pytest.approx(51.0, abs=3.0)  # not the 13.9 km city-anchor figure


def test_hotel_morning_to_scheduled_remote_gets_access_chain():
    """占位晨卡 → 远郊班次点：成对并出接驳链（不是直线打车腿）。

    晨卡位置（城市锚）写回 anchor_location 后，access_breakdown 的起点取得到，
    算得出「打车到乘车点 + 候车 + 专线」链——与带锚晨卡（test_leg_fares 三条）
    同形，不需要任何特判。
    """
    plan = _plan(
        [
            _morning(),
            _v(
                "r1",
                "慕田峪长城",
                time(10, 40),
                time(14, 40),
                loc=REMOTE,
                access_mode="shuttle",
                access_service_minutes=90,
                access_boarding_stop="前门大街北口",
                access_boarding=GeoPoint(lon=116.3982, lat=39.8988),
            ),
        ]
    )
    assert _ids(plan) == [("hotel-morning-d1", "r1")]
    annotate_legs(plan)
    leg = plan.days[0].items[0]
    assert leg.next_leg_mode == "access"
    assert (leg.next_leg_detail or {}).get("direction") != "return"


def test_hotel_night_card_stays_transparent():
    # 末站→夜卡不在这里成对（回城链/回城卡口径不动）。
    plan = _plan(
        [
            _v("s1", "天坛", time(9, 0), time(11, 0), loc=TEMPLE_OF_HEAVEN),
            _v(
                "hotel-night-d1",
                "回酒店·夜间休息",
                time(21, 0),
                time(21, 30),
                cat="hotel",
            ),
        ]
    )
    assert _ids(plan) == []


def test_remote_last_stop_return_chain_untouched():
    # 末站是班次点：回城三段链照旧挂上（城市锚回退没有碰 _point）。
    plan = _plan(
        [
            _v(
                "r1",
                "慕田峪长城",
                time(10, 40),
                time(14, 40),
                loc=REMOTE,
                access_mode="shuttle",
                access_service_minutes=90,
                access_last_mile_minutes=8,
                access_boarding_stop="前门大街北口",
                access_alight_stop="前门大街北口",
                access_boarding=GeoPoint(lon=116.397, lat=39.899),
                access_return_times=["14:30", "15:30", "16:30"],
            ),
            _v(
                "hotel-night-d1",
                "回酒店·夜间休息",
                time(21, 0),
                time(21, 30),
                cat="hotel",
            ),
        ]
    )
    annotate_legs(plan)
    site = plan.days[0].items[0]
    assert site.next_leg_mode == "access"
    assert (site.next_leg_detail or {}).get("direction") == "return"


# ---------------------------------------------------------------------------
# 1) bridge card carries the same leg fields as the card footer
# ---------------------------------------------------------------------------


def _two_site_plan(tail=False):
    items = [
        _v("s1", "天坛", time(9, 0), time(11, 0), loc=TEMPLE_OF_HEAVEN),
        _v("s2", "颐和园", time(12, 30), time(15, 0), loc=SUMMER_PALACE),
    ]
    if tail:
        items.append(
            _v(
                "hotel-night-d1",
                "回酒店·夜间休息",
                time(21, 0),
                time(21, 30),
                cat="hotel",
            )
        )
    return _plan(items)


def _bridge(plan):
    return next(
        (
            i
            for i in plan.days[0].items
            if str(i.item_id or "").startswith("leg-bridge-")
        ),
        None,
    )


def test_bridge_card_inherits_annotated_leg_fields():
    plan = _two_site_plan()
    annotate_legs(plan)
    src = plan.days[0].items[0]
    attach_gap_bridges(plan)
    br = _bridge(plan)
    assert br is not None
    assert br.distance_to_next_km == src.distance_to_next_km
    assert br.next_leg_mode == src.next_leg_mode
    assert br.next_leg_minutes == src.next_leg_minutes
    assert br.next_leg_cost_cny == src.next_leg_cost_cny
    assert br.next_walk_minutes is not None
    # 名字不带目的地名（既有口径不动）
    assert "颐和园" not in (br.name or "")


def test_bridge_card_estimates_when_prev_has_no_annotated_leg():
    plan = _two_site_plan()
    # 不跑 annotate：前卡没有腿字段，桥卡按坐标+价目表现估
    attach_gap_bridges(plan)
    br = _bridge(plan)
    assert br is not None
    assert br.distance_to_next_km == pytest.approx(16.5, abs=1.5)
    assert br.next_leg_mode in ("taxi", "walk")
    assert isinstance(br.next_leg_minutes, int) and br.next_leg_minutes > 0
    if br.next_leg_mode == "taxi":
        assert isinstance(br.next_leg_cost_cny, (int, float))


def test_bridge_card_leaves_fields_empty_without_coordinates():
    plan = _plan(
        [
            _v("s1", "甲", time(9, 0), time(11, 0)),
            _v("s2", "乙", time(12, 30), time(15, 0)),
        ]
    )
    attach_gap_bridges(plan)
    br = _bridge(plan)
    assert br is not None
    assert br.distance_to_next_km is None
    assert br.next_leg_minutes is None


def test_h5_unified_leg_row_wiring_and_syntax(tmp_path):
    """H5 守门：统一腿行的接线在位，且内联脚本语法成立。

    站间交通腿只许一种呈现——[出发时刻] 距下一站 X km · 车程/步行/接驳约
    N 分钟 · 约 ¥Y，行右 TAXI + ALL TRANSPORTATION。接线断言守住三件事：
    页脚只在「没有紧跟桥卡」时出、桥卡卡名位走同一构造器、回程结构化块里
    与页脚重复的打车行让位。内联脚本逐块过 ``node --check``——R39 实锤：
    整段替换吃掉了一个 ``if`` 开括号，只有语法检查能在提交前抓住。
    """
    import re
    import shutil
    import subprocess
    from pathlib import Path

    static = Path(__file__).resolve().parents[1] / "app" / "static"
    html = (static / "index.html").read_text(encoding="utf-8")

    assert "function legRowParts(it, items, idx) {" in html
    assert "function navAllTransportTo(name, lon, lat) {" in html
    assert "if (hasKm && !isBridgeCard && !bridgeFollows) {" in html  # 页脚闸
    assert "const brRow = isBridgeCard ? legRowParts(it, d.items, idx) : null;" in html
    assert "if (isRet && !hasKm && (Number(legD.taxi_km) || 0) > 0.05) {" in html
    # 页脚：出发时刻在前、按钮在右
    assert '\'<span class="t" style="flex:0 0 auto">\' + depTxt + "</span>"' in html
    assert (
        "'<span style=\"flex:0 0 auto;white-space:nowrap\">' + rowParts.buttons" in html
    )
    # R39b：腿行/桥卡用隐藏把手占位，时间列与站点卡对齐；按钮紧跟文字并排
    assert "const timePad = (planSession && planSession.session_id)" in html
    assert (
        '<span class="drag-handle" style="visibility:hidden" aria-hidden="true">'
        "⠿</span>" in html
    )
    # 按钮与跳转：TAXI 复用 calltaxi；ALL TRANSPORTATION 落导航页
    # （起点=当前位置、终点=下一景点）
    assert 'button[data-action="navall"]' in html
    assert 'navAllTransportTo(na.getAttribute("data-name")' in html
    assert '#modeBar button[data-mode="driving"]' in html
    # 同址占位桥卡（两端 <0.05km）：不出按钮、不挂整卡导航；
    # 链接内词条去前导分隔符，免出「· ·」双点
    assert 'it.next_leg_mode === "same_venue"' in html
    assert '(isBridgeLeg && it.next_leg_mode !== "same_venue")' in html
    assert "const stripDot = (s) => String(s).replace(" in html

    i18n = (static / "i18n.js").read_text(encoding="utf-8")
    assert '"card.allTransport": "🧭 ALL TRANSPORTATION"' in i18n
    assert '"card.allTransport.title": "Open the Navigation tab' in i18n

    node = shutil.which("node")
    if node is None:
        pytest.skip("node not on PATH — inline script syntax not checked")
    targets = []
    for m in re.finditer(
        r"<script(?P<attrs>[^>]*)>(?P<body>.*?)</script>", html, flags=re.S
    ):
        attrs = m.group("attrs") or ""
        if re.search(r"\bsrc\s*=", attrs) or "json" in attrs:
            continue
        f = tmp_path / ("inline_%d.js" % len(targets))
        f.write_text(m.group("body"), encoding="utf-8")
        targets.append(f)
    for name in ("sw.js", "i18n.js"):
        targets.append(static / name)
    assert targets, "no inline script block found"
    for f in targets:
        r = subprocess.run(
            [node, "--check", str(f)], capture_output=True, text=True, encoding="utf-8"
        )
        assert r.returncode == 0, "%s: %s" % (f.name, (r.stderr or "")[:400])


def test_morning_with_anchor_keeps_access_chain_to_scheduled_stop():
    """晨卡自带锚点（location=None + anchor_location=城市锚）→ 远郊班次点：基线就成对
    出接驳链（test_leg_fares 三条的形状）。「不叠直线腿」只约束自身无坐标/锚点、
    位置靠城市锚回退的占位晨卡——第一版规则连带锚晨卡一起跳掉，把这三条打红。"""
    morning = _v(
        "hotel-morning-d1",
        "从酒店出发",
        time(8, 30),
        time(9, 0),
        cat="hotel",
        dur=0,
        anchor_location=GeoPoint(lon=116.4074, lat=39.9042),
    )
    plan = _plan(
        [
            morning,
            _v(
                "r1",
                "慕田峪长城",
                time(10, 40),
                time(14, 40),
                loc=REMOTE,
                access_mode="shuttle",
                access_service_minutes=90,
                access_boarding_stop="前门大街北口",
                access_boarding=GeoPoint(lon=116.3982, lat=39.8988),
            ),
        ]
    )
    assert _ids(plan) == [("hotel-morning-d1", "r1")]
    annotate_legs(plan)
    leg = plan.days[0].items[0]
    assert leg.next_leg_mode == "access"
    assert (leg.next_leg_detail or {}).get("direction") != "return"


def test_hotel_morning_position_written_back_to_anchor_location():
    """leg_pairs 的契约：成对的卡必有取值点（location 或 anchor_location）。

    R39 线上 500 实锤：晨卡位置只在链内用城市锚算、没写回卡上——读路径
    _enrich_legs 对成对前卡取 _leg_point(a).lon 做图商实测回填，拿到 None
    直接 AttributeError，带无坐标晨卡的会话 GET /plan 全部 500。
    """
    from app.services.agent.plan import _leg_point

    plan = _plan(
        [_morning(), _v("s1", "颐和园", time(9, 20), time(11, 55), loc=SUMMER_PALACE)]
    )
    assert _ids(plan) == [("hotel-morning-d1", "s1")]
    morning = plan.days[0].items[0]
    assert morning.location is None  # 占位晨卡没有真坐标
    assert morning.anchor_location is not None  # 城市锚写回卡上
    assert _leg_point(morning) is not None


def test_get_plan_with_coordless_morning_card_does_not_500():
    """读盘路径回归（R39 线上 500 实锤）：agent 带 amap（生产形态）时，

    无坐标晨卡的会话 GET /api/v1/plan/{sid} 必须 200，且晨卡带出到第一个
    景点的腿。测试环境默认没有 amap，_enrich_legs 开头就 return——必须显式
    挂一个 amap stub 才覆盖得到炸点。
    """
    from fastapi.testclient import TestClient

    from app.api.plan import get_plan_sessions
    from app.services.agent.plan import PlanningAgent, PlanSession
    from tests.test_plan_api import StubAdapter, make_app

    class _Amap:
        vendor = "stub"

        async def walking_route(
            self, origin, destination, *, origin_id=None, destination_id=None
        ):
            return {"distance_m": 16000, "duration_s": 32 * 60}

    agent = PlanningAgent(StubAdapter([]))
    agent._amap = _Amap()
    app = make_app(agent)
    store = app.dependency_overrides[get_plan_sessions]()
    store.save(
        PlanSession(
            session_id="s-r39-morning",
            device_id="device-r39",
            state="ready",
            plan=ItineraryPlan(
                itinerary_id="it-r39",
                cities=["北京"],
                days=[
                    DayPlan(
                        day=1,
                        base_city="北京",
                        items=[
                            _morning(),
                            _v(
                                "s1",
                                "颐和园",
                                time(9, 20),
                                time(11, 55),
                                loc=SUMMER_PALACE,
                            ),
                        ],
                    )
                ],
            ),
        )
    )
    with TestClient(app, headers={"X-Device-ID": "device-r39"}) as client:
        r = client.get("/api/v1/plan/s-r39-morning")
    assert r.status_code == 200, r.text
    items = {i["item_id"]: i for i in r.json()["plan"]["days"][0]["items"]}
    assert items["hotel-morning-d1"]["distance_to_next_km"] is not None


def test_bridge_after_anchored_placeholder_meal_estimates_from_anchor():
    """上一张是锚定占位餐卡（没有 location，位置在锚点上）：桥卡兜底估算吃锚点。

    此前只认 location → 算不出分钟 → 桥卡名落「🧭 前往下一站（自由安排）」、统一
    字段只有距离没有车程/费用（用户实报的第二种格式残留：live 会话 591c9e98
    午饭 13:00 → 圆明园 13:37 实锤）。
    """
    site = _v("s1", "颐和园", time(9, 0), time(13, 0), loc=SUMMER_PALACE)
    lunch = VisitItem(
        item_id="food-lunch-ph-d1",
        name="午饭（自由安排）",
        city="北京",
        day=1,
        category="food",
        start_time=time(12, 0),
        end_time=time(13, 0),
        duration_minutes=60,
        anchor_from_prev=True,
        anchor_location=GeoPoint(lon=SUMMER_PALACE[0], lat=SUMMER_PALACE[1]),
    )
    nxt = _v("s2", "圆明园", time(13, 37), time(14, 22), loc=(116.30, 40.01))
    plan = _plan([site, lunch, nxt])
    attach_gap_bridges(plan)  # 不跑 annotate：午饭卡没有腿字段 → 走桥卡兜底估算
    br = _bridge(plan)
    assert br is not None
    assert br.start_time == time(13, 0) and br.end_time == time(13, 37)
    assert br.next_leg_mode == "taxi"
    assert isinstance(br.next_leg_minutes, int) and br.next_leg_minutes > 0
    assert isinstance(br.next_leg_cost_cny, (int, float))
    assert br.distance_to_next_km == pytest.approx(3.3, abs=0.6)  # 颐和园锚点 → 圆明园
    assert "自由安排" not in (br.name or "")


def test_bridge_between_same_venue_cards_is_marked_same_venue():
    """两端同址的桥卡（午饭就锚在刚逛完的景点里，距离≈0）：不是一段交通。

    此前兜底估算对 0km 返回 None → 桥卡名落「🧭 前往下一站（自由安排）」，统一后
    又被挂上打车/导航按钮，指向同址的午饭（live 会话 09247aac Day2 天坛 11:30 →
    午餐 11:35 实锤）。标 same_venue：前端出「同址 · 就在附近」且不出按钮。
    """
    temple = _v("v4", "天坛", time(9, 0), time(11, 30), loc=TEMPLE_OF_HEAVEN)
    lunch = VisitItem(
        item_id="meal-lunch-2",
        name="午餐",
        city="北京",
        day=1,
        category="food",
        start_time=time(11, 35),
        end_time=time(12, 35),
        duration_minutes=60,
        anchor_from_prev=True,
        anchor_location=GeoPoint(lon=TEMPLE_OF_HEAVEN[0], lat=TEMPLE_OF_HEAVEN[1]),
    )
    plan = _plan([temple, lunch])
    attach_gap_bridges(plan)
    br = _bridge(plan)
    assert br is not None
    assert br.next_leg_mode == "same_venue"
    # R39 收口：同址也算一段腿——给真实微距 + 步行 1 分钟（前端不再走「同址」文案）
    assert br.distance_to_next_km == pytest.approx(0.0, abs=0.02)
    assert br.next_walk_minutes == 1
    assert br.next_leg_minutes is None
    assert "同址" in (br.name or "")
    assert "自由安排" not in (br.name or "") and "前往下一站" not in (br.name or "")
    assert br.name_en  # 英文界面有对应文案
    # 桥卡名不内嵌目的地名（既有口径）
    assert "午餐" not in (br.name or "")


def test_open_meal_leg_gaps_respects_night_card_boundary():
    """嵌套同址晚饭后的顺延不得压到夜卡（rule1 重叠横幅的根因）。

    R39 实锤（用户会话 09247aac Day3）：晚饭 18:35-19:20 与奥园同址嵌套，顺延只查
    day_end 21:30，把末站鸟巢推到 21:20，压到 21:16 起的夜卡上 → 出站横幅
    「鸟巢(国家体育场)(20:35-21:20) 与 回酒店(21:16-21:30) 时间区间重叠」。
    钉住件（夜卡）是硬边界：顺延会压线就整段不动（保持嵌套原态，rule1 不报）。
    """
    from app.services.agent.plan import _open_meal_leg_gaps

    dinner = VisitItem(
        item_id="meal-dinner-3",
        name="晚饭",
        city="北京",
        day=1,
        category="food",
        start_time=time(17, 0),
        end_time=time(17, 45),
        duration_minutes=45,
        anchor_from_prev=True,
        anchor_location=GeoPoint(lon=116.0, lat=39.8),
    )
    v9 = _v("v9", "奥林匹克公园", time(17, 45), time(18, 30), loc=(116.39, 40.00))
    v10 = _v("v10", "鸟巢(国家体育场)", time(18, 30), time(19, 15), loc=(116.39, 40.01))
    night = _v(
        "hotel-night-d3", "回酒店·夜间休息", time(19, 40), time(20, 10), cat="hotel"
    )
    plan = _plan([dinner, v9, v10, night])
    _open_meal_leg_gaps(plan)
    assert v10.end_time is not None
    assert str(v10.end_time)[:5] <= str(night.start_time)[:5], (
        "顺延把末站压到夜卡上: v10 %s-%s vs night %s"
        % (str(v10.start_time)[:5], str(v10.end_time)[:5], str(night.start_time)[:5])
    )


def test_make_room_for_meal_stops_at_night_card(monkeypatch):
    """餐卡让位链遇夜卡即整段失败（rule1 重叠横幅的第二条路径）。

    R39 实锤（会话 09247aac Day3）：晚饭 18:35-19:20 与 45 分钟奥园同窗（不足 3 小时
    大点、不算嵌套宿主），_make_room_for_meal 把奥园/鸟巢整体右推，只查 day_end 21:30
    不看夜卡 21:16 → 鸟巢 20:35-21:20 压夜卡。让位链压线=整段失败，一个字节都不动。
    """
    from app.services.agent import plan as plan_mod

    monkeypatch.setattr(plan_mod, "generic_entry_cap", lambda *a, **k: None)

    dinner = VisitItem(
        item_id="meal-dinner-3",
        name="晚饭",
        city="北京",
        day=1,
        category="food",
        start_time=time(18, 35),
        end_time=time(19, 20),
        duration_minutes=45,
    )
    v9 = _v("v9", "奥林匹克公园", time(18, 35), time(19, 20), loc=(116.39, 40.00))
    v10 = _v("v10", "鸟巢(国家体育场)", time(19, 53), time(20, 38), loc=(116.39, 40.01))
    night = _v(
        "hotel-night-d3", "回酒店·夜间休息", time(21, 16), time(21, 30), cat="hotel"
    )
    day = _plan([dinner, v9, v10, night]).days[0]
    ok = plan_mod._make_room_for_meal(day, dinner, 18 * 60 + 35, 45)
    assert ok is False
    assert str(v9.start_time)[:5] == "18:35"
    assert str(v10.end_time)[:5] == "20:38"


def _r39c_day():
    """与用户会话 Day3 同形：午饭 12:00-13:00、晚饭 18:35-19:20 与 45 分钟奥园同窗
    （不足 3 小时、不算嵌套宿主），鸟巢 19:53-20:38。午/晚餐卡齐全，_ensure_meal_cards
    不会补卡，只有「重叠对账」会改动该天。"""
    site = _v("v8", "天坛", time(9, 0), time(11, 30), loc=(116.41, 39.88))
    lunch = VisitItem(
        item_id="meal-lunch-3",
        name="午餐",
        city="北京",
        day=1,
        category="food",
        start_time=time(12, 0),
        end_time=time(13, 0),
        duration_minutes=60,
    )
    dinner = VisitItem(
        item_id="meal-dinner-3",
        name="晚饭",
        city="北京",
        day=1,
        category="food",
        start_time=time(18, 35),
        end_time=time(19, 20),
        duration_minutes=45,
    )
    v9 = _v("v9", "奥林匹克公园", time(18, 35), time(19, 20), loc=(116.39, 40.00))
    v10 = _v("v10", "鸟巢(国家体育场)", time(19, 53), time(20, 38), loc=(116.39, 40.01))
    return [site, lunch, dinner, v9, v10]


def _starts(plan):
    return {
        i.item_id: str(i.start_time)[:5]
        for i in plan.days[0].items
        if getattr(i, "start_time", None) is not None
    }


def test_ensure_meal_cards_reconcile_false_keeps_engine_shape():
    """R39c：keep/both（引擎盘）不跑餐卡重叠对账——引擎排的嵌套/顺延不被读路径重排。"""
    from app.services.agent.plan import _ensure_meal_cards

    kept = _plan(_r39c_day())
    base = _starts(kept)
    _ensure_meal_cards(kept, reconcile=False)
    assert _starts(kept) == base, "引擎盘：读路径一个时刻都不许改"

    shuffled = _plan(_r39c_day())
    _ensure_meal_cards(shuffled, reconcile=True)
    assert _starts(shuffled) != base, (
        "对照：legacy 对账应改动该天（景点顺延或餐卡另置）"
    )


def test_plan_turn_body_keep_session_does_not_refow_meals():
    """R39c：GET/回合响应里，keep 会话保持引擎盘时刻；legacy 会话照旧对账。"""
    from app.api.plan import _plan_turn_body
    from app.services.agent.plan import PlanSession

    def body_for(seq):
        session = PlanSession(
            session_id="s-r39c-%s" % (seq or "legacy"),
            device_id="dev-r39c",
            state="ready",
            sequence_choice=seq,
            plan=_plan(_r39c_day()),
        )
        body = _plan_turn_body(session, None, None)
        return _starts(body["plan"])

    keep_items = body_for("keep")
    assert keep_items["v9"] == "18:35"
    assert keep_items["v10"] == "19:53"

    legacy_items = body_for(None)
    assert legacy_items != keep_items, "对照：legacy 会话应仍走餐卡对账（时刻有变化）"


# ---- R39d（2026-11-25）：任何两个 SITES（含午/晚餐）之间都要有交通腿 ----
def _r39d_day():
    """Day1 形状：颐和园 09:32-13:32（卡内 12:00 午饭）→ 圆明园 14:02。"""
    sight = _v("v1", "颐和园", time(9, 32), time(13, 32), loc=(116.2755, 39.9999))
    lunch = VisitItem(
        item_id="food-lunch-ph-d1",
        name="午饭（自由安排）",
        city="北京",
        day=1,
        category="food",
        start_time=time(12, 0),
        end_time=time(13, 0),
        duration_minutes=60,
        anchor_from_prev=True,
        location=GeoPoint(lon=116.2755, lat=39.9999),
    )
    after = _v("v2", "圆明园", time(14, 2), time(14, 47), loc=(116.2974, 40.0084))
    return [sight, lunch, after]


def test_leg_pairs_keeps_nested_meal_pair():
    """卡内午饭（12:00 落在 13:32 收尾的游览里）与上一站同址，仍要成腿。"""
    from app.services.itinerary.legs import leg_pairs

    plan = _plan(_r39d_day())
    pairs = [(a.item_id, b.item_id, round(km, 3)) for a, b, km in leg_pairs(plan)]
    assert ("v1", "food-lunch-ph-d1", 0.0) in pairs, pairs


def test_leg_pairs_keeps_same_venue_meal_even_when_not_nested():
    """同址但不嵌套（午饭排在同一站收尾之后）也要成腿——R39d 用户令。

    例外两种：①上一站是班次点/远郊（回城专线链优先）；②上一站也是餐卡
    （餐↔餐不连 0km 假腿）。
    """
    from app.services.itinerary.legs import leg_pairs

    items = _r39d_day()
    items[1].start_time = time(13, 32)
    items[1].end_time = time(14, 2)
    items[2].start_time = time(14, 32)
    day = items
    plan = _plan(day)
    pairs = [(a.item_id, b.item_id) for a, b, _km in leg_pairs(plan)]
    assert ("v1", "food-lunch-ph-d1") in pairs, pairs  # 同址也成腿
    # 午饭→圆明园照常有腿（2.09 km）
    assert ("food-lunch-ph-d1", "v2") in pairs, pairs


def test_annotate_nested_meal_leg_is_zero_km_walk():
    """嵌套餐卡的腿注解=0.0 km、步行 1 分钟（不是打车）。"""
    from app.services.itinerary.legs import annotate_legs

    plan = _plan(_r39d_day())
    annotate_legs(plan)
    sight, lunch, after = plan.days[0].items
    # 腿挂在「上一站」卡页脚：颐和园 → 卡内午饭 = 0.0 km 步行
    assert sight.distance_to_next_km == 0.0, sight.distance_to_next_km
    assert sight.next_leg_mode == "walk", sight.next_leg_mode
    assert sight.next_leg_minutes == 1, sight.next_leg_minutes
    # 午饭自身去下一站照常有腿
    assert lunch.distance_to_next_km is not None and lunch.distance_to_next_km > 0


def test_h5_footer_uses_nested_departure_time():
    """页脚出发时刻取嵌套件起点（12:00），bridgeFollows 不再隐藏嵌套页脚。"""
    from pathlib import Path

    html = (
        Path(__file__).resolve().parents[1] / "app" / "static" / "index.html"
    ).read_text(encoding="utf-8")
    assert "let depTxt = fmtTime(it.end_time);" in html
    assert "depTxt = fmtTime(nxtItem.start_time);" in html
    assert '\'<span class="t" style="flex:0 0 auto">\' + depTxt' in html
    # 嵌套存在时不隐藏页脚
    assert "if (nested) return false;" in html
