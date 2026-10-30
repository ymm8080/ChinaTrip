"""确定性选点主路径（2026-10-28 用户拍板：规划=特定算法，非通用 LLM；暂不评分）。

覆盖：首次到访 tier 序（08 UNESCO>02 5A>05 国际网站>10 国际平台>04 演出>
12 小红书>01 街区>风景名胜区）、地理聚拢分日（同片区同天）、每日参访时长
预算、4 个/日闸、演出城市末日收尾、餐饮锚点全保留摊开、无坐标候选均衡
分日、确定性、天数夹紧；算法模式下 v0 生成零 LLM 调用；备用模式仍走
_select_pois；zhipu 适配器思考模式默认关断。
"""

from __future__ import annotations

import asyncio
import json

import httpx

from app.services.agent.plan import PlanningAgent
from app.services.itinerary import VisitItem
from app.services.llm.base import ChatResult
from app.services.llm.zhipu import ZhipuGLMAdapter
from app.services.restaurants import MEAL_DURATION_MINUTES

# 人民广场 / 浦东 两个相距 ~8km 的坐标簇（lon, lat）
_SQ = (121.4737, 31.2304)
_PD = (121.5440, 31.2214)


def _cand(
    name: str,
    city: str,
    *,
    cat: str = "sight",
    show: bool = False,
    suggested=None,
    tags=None,
    loc=None,
):
    c: dict = {"name": name, "city": city, "category": cat}
    if show:
        c["best_visit_time"] = "show"
    if suggested is not None:
        c["suggested_duration_min"] = suggested
    if tags is not None:
        c["tags"] = tags
    if loc is not None:
        c["location"] = loc
    return c


class BoomLLM:
    """算法模式下任何 LLM 调用都是事故——直接炸。"""

    async def chat(self, messages, *, temperature=0.3, max_tokens=None) -> ChatResult:
        raise AssertionError("algorithm mode must not call the LLM")


# --- tier 序（用户拍板首次到访优先级） --------------------------------------


def test_algo_tier_priority_first_visit():
    cands = [
        _cand("普通甲", "成都"),
        _cand("小红书店", "成都", tags=["xiaohongshu"]),
        _cand("国际平台点", "成都", tags=["sygic"]),
        _cand("五A区", "成都", tags=["5a"]),
        _cand("世遗点", "成都", tags=["unesco"]),
        _cand("普通乙", "成都"),
    ]
    items = PlanningAgent._deterministic_selection(cands, 1, {"成都": (1, 1)})
    # span=1：pool=前 4（tier 序），全部入计划（240 分钟 ≤ 预算，4 个/日闸）
    assert [it["name"] for it in items] == ["世遗点", "五A区", "国际平台点", "小红书店"]


def test_algo_tier_uses_source_column():
    cands = [
        _cand("库藏点", "成都"),
        _cand(
            "unesco源点",
            "成都",
            tags=[],
        ),
    ]
    cands[1]["source"] = "unesco"
    items = PlanningAgent._deterministic_selection(cands, 1, {"成都": (1, 1)})
    assert items[0]["name"] == "unesco源点"


# --- 地理聚拢分日 -----------------------------------------------------------


def test_geo_cluster_same_area_same_day():
    sq = [
        _cand("人民广场五A", "上海", tags=["5a"], loc=(_SQ[0], _SQ[1])),
        _cand("南京东路", "上海", loc=(_SQ[0] + 0.002, _SQ[1] - 0.001)),
        _cand("博物馆", "上海", loc=(_SQ[0] - 0.002, _SQ[1] + 0.002)),
    ]
    pd = [
        _cand("东方明珠", "上海", loc=(_PD[0], _PD[1])),
        _cand("海洋馆", "上海", loc=(_PD[0] + 0.002, _PD[1] + 0.001)),
        _cand("滨江大道", "上海", loc=(_PD[0] - 0.001, _PD[1] - 0.002)),
    ]
    items = PlanningAgent._deterministic_selection(sq + pd, 2, {"上海": (1, 2)})
    by_day = {}
    for it in items:
        by_day.setdefault(it["day"], set()).add(it["name"])
    # 含 tier 最高（5A）的簇排第 1 天，同簇同天
    assert by_day[1] == {"人民广场五A", "南京东路", "博物馆"}
    assert by_day[2] == {"东方明珠", "海洋馆", "滨江大道"}


# --- 每日时间预算与 4 个/日闸 -----------------------------------------------


def test_time_budget_drops_when_day_full():
    cands = [
        _cand("甲", "成都", suggested=180, loc=(104.06, 30.66)),
        _cand("乙", "成都", suggested=180, loc=(104.06, 30.66)),
        _cand("丙", "成都", suggested=180, loc=(104.06, 30.66)),
    ]
    items = PlanningAgent._deterministic_selection(cands, 1, {"成都": (1, 1)})
    # 180+180=360 满，第三个出局
    assert len(items) == 2


def test_four_per_day_cap():
    cands = [
        _cand(f"点{i}", "成都", suggested=30, loc=(104.06, 30.66)) for i in range(6)
    ]
    items = PlanningAgent._deterministic_selection(cands, 1, {"成都": (1, 1)})
    assert len(items) == 4  # 时长够但 4 个/日闸封顶


# --- 分日语义（无坐标候选：均衡摊日） ---------------------------------------


def test_algo_balances_no_coord_sights_across_days():
    cands = [_cand(f"成都景点{i:02d}", "成都市") for i in range(8)]
    items = PlanningAgent._deterministic_selection(cands, 2, {"成都": (1, 2)})
    assert len(items) == 8  # pool=span*4，全部放下（每 60 分钟）
    by_day = {}
    for it in items:
        by_day.setdefault(it["day"], set()).add(it["name"])
    assert by_day[1] == {"成都景点00", "成都景点02", "成都景点04", "成都景点06"}
    assert by_day[2] == {"成都景点01", "成都景点03", "成都景点05", "成都景点07"}
    assert items[0]["city"] == "成都市"
    assert items[0]["duration_minutes"] == 60


def test_algo_respects_city_windows():
    cands = [_cand(f"渝{i}", "重庆") for i in range(4)]
    cands += [_cand(f"蓉{i}", "成都") for i in range(4)]
    items = PlanningAgent._deterministic_selection(
        cands, 4, {"成都": (1, 2), "重庆": (3, 4)}
    )
    days = {it["name"]: it["day"] for it in items}
    assert sorted(d for n, d in days.items() if n.startswith("蓉")) == [1, 1, 2, 2]
    assert sorted(d for n, d in days.items() if n.startswith("渝")) == [3, 3, 4, 4]


# --- 演出 / 餐饮 / 夹紧 / 确定性 --------------------------------------------


def test_algo_show_closes_city_last_day_and_extra_shows_dropped():
    cands = [
        _cand("宽窄巷子", "成都"),
        _cand("变脸表演", "成都", cat="entertainment", suggested=105),
        _cand("蜀风雅韵", "成都", show=True),  # 第二场演出不排（每城一场）
        _cand("人民公园", "成都"),
    ]
    items = PlanningAgent._deterministic_selection(cands, 3, {"成都": (1, 3)})
    show = next(it for it in items if it["name"] == "变脸表演")
    assert show["day"] == 3  # 城市末日收尾
    assert show["duration_minutes"] == 105  # 库建议时长优先
    assert "蜀风雅韵" not in {it["name"] for it in items}


def test_algo_show_without_suggested_defaults_90():
    cands = [_cand("川剧秀", "成都", cat="entertainment")]
    items = PlanningAgent._deterministic_selection(cands, 2, {"成都": (1, 2)})
    assert items[0]["duration_minutes"] == 90


def test_algo_foods_all_kept_and_spread():
    cands = [_cand(f"店{i}", "成都", cat="food") for i in range(3)]
    cands.append(_cand("宽窄巷子", "成都"))
    items = PlanningAgent._deterministic_selection(cands, 2, {"成都": (1, 2)})
    foods = [it for it in items if it["name"].startswith("店")]
    assert len(foods) == 3  # 餐饮锚点全保留
    assert sorted(it["day"] for it in foods) == [1, 1, 2]  # 摊到窗口各天
    assert all(it["duration_minutes"] == MEAL_DURATION_MINUTES for it in foods)


def test_algo_needs_no_rating_fields_and_is_deterministic():
    cands = [_cand(f"景点{i}", "上海", show=(i == 5)) for i in range(9)]
    assert all("rating" not in c and "rating_count" not in c for c in cands)
    a = PlanningAgent._deterministic_selection(cands, 2, {"上海": (1, 2)})
    b = PlanningAgent._deterministic_selection(list(cands), 2, {"上海": (1, 2)})
    assert a == b
    assert len(a) == 9  # 8 游览点（每日闸 4×2 天全放下）+ 1 场演出


def test_algo_clamps_day_into_total_days():
    cands = [
        _cand("演出", "成都", cat="entertainment"),
        _cand("景点", "成都"),
    ]
    items = PlanningAgent._deterministic_selection(cands, 3, {"成都": (1, 4)})
    show = next(it for it in items if it["name"] == "演出")
    assert show["day"] == 3  # 窗口越界被夹到总天数


# --- 流程：算法模式生成 v0，零 LLM 调用 --------------------------------------


def test_v0_algorithm_mode_generates_without_llm(monkeypatch):
    monkeypatch.delenv("PLAN_SELECT_MODE", raising=False)
    agent = PlanningAgent(BoomLLM())
    session = asyncio.run(
        agent.start(device_id="d1", cities=["上海"], days=2, preferences="博物馆")
    )
    assert session.state == "ready"
    assert any("特定算法" in a or "库顺序" in a for a in session.assumptions)
    names = {
        i.name for d in session.plan.days for i in d.items if isinstance(i, VisitItem)
    }
    assert "上海博物馆" in names
    assert "上海地标" in names


def test_v0_llm_mode_still_selects_via_llm(monkeypatch):
    """备用模式仍走 _select_pois（回滚开关有效）。"""
    monkeypatch.setenv("PLAN_SELECT_MODE", "llm")
    replies = [
        json.dumps(
            {
                "items": [
                    {
                        "name": "上海博物馆",
                        "city": "上海",
                        "category": "sight",
                        "day": 1,
                    }
                ],
                "assumptions": [],
            },
            ensure_ascii=False,
        )
    ]

    class OneShotLLM:
        def __init__(self):
            self.calls = 0

        async def chat(self, messages, *, temperature=0.3, max_tokens=None):
            self.calls += 1
            return ChatResult(content=replies[0], model="scripted")

    llm = OneShotLLM()
    agent = PlanningAgent(llm)
    session = asyncio.run(
        agent.start(device_id="d1", cities=["上海"], days=1, preferences="博物馆")
    )
    assert session.state == "ready"
    assert llm.calls >= 1
    names = {
        i.name for d in session.plan.days for i in d.items if isinstance(i, VisitItem)
    }
    assert "上海博物馆" in names


# --- zhipu 适配器：思考默认关断 ----------------------------------------------


def _capture_adapter():
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.read()))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
                "usage": {},
            },
        )

    adapter = ZhipuGLMAdapter(
        api_key="k",
        base_url="https://t.test",
        model="m",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )
    return adapter, captured


def test_zhipu_chat_thinking_disabled_by_default():
    from app.services.llm.base import ChatMessage

    adapter, captured = _capture_adapter()
    asyncio.run(adapter.chat([ChatMessage(role="user", content="hi")]))
    assert captured[0].get("thinking") == {"type": "disabled"}


def test_zhipu_chat_thinking_true_opt_back_in():
    from app.services.llm.base import ChatMessage

    adapter, captured = _capture_adapter()
    asyncio.run(adapter.chat([ChatMessage(role="user", content="hi")], thinking=True))
    assert "thinking" not in captured[0]


def test_zhipu_extract_thinking_disabled():
    adapter, captured = _capture_adapter()
    asyncio.run(adapter.extract("看看这段文本", lang="zh"))
    assert captured[0].get("thinking") == {"type": "disabled"}


def test_transfer_day_budget_reduced():
    """转场日（车票/机票钉死）预算扣 180：满额天放得下的量在转场日放不下。"""
    cands = [
        _cand("甲", "成都", suggested=120, loc=(104.06, 30.66)),
        _cand("乙", "成都", suggested=120, loc=(104.06, 30.66)),
        _cand("丙", "成都", suggested=120, loc=(104.06, 30.66)),
    ]
    full = PlanningAgent._deterministic_selection(cands, 1, {"成都": (1, 1)})
    assert len(full) == 3  # 120×3=360 恰好满额全放
    pinned = PlanningAgent._deterministic_selection(
        cands, 1, {"成都": (1, 1)}, transfer_days={1}
    )
    # 转场日预算 360-180=180：第一个 120 放得下，第二个 240>180 出局
    assert len(pinned) == 1


def test_transfer_days_only_deduct_listed_days():
    cands = [_cand(f"点{i}", "成都", suggested=60) for i in range(6)]
    items = PlanningAgent._deterministic_selection(
        cands, 2, {"成都": (1, 2)}, transfer_days={1}
    )
    by_day = {}
    for it in items:
        by_day.setdefault(it["day"], set()).add(it["name"])
    # day1 预算 180：3 个；day2 满额：3 个（池 span*4=8 全放，各 3）
    assert len(by_day[1]) == 3
    assert len(by_day.get(2, set())) == 3


# --- 2026-10-30 过载优化：走行计预算 + 必去容量感知放日 --------------------


def test_travel_legs_count_into_day_budget():
    """远距两点的走行腿（封顶 120）计入当日预算：150+150+120=420>360，
    第二点出局——旧口径只算参访时长（300≤360）两个都放，solver 只能
    排出物理不可能的背靠背日程。"""
    cands = [
        _cand("甲", "成都", suggested=150, loc=(104.06, 30.66)),
        _cand("乙", "成都", suggested=150, loc=(104.90, 31.20)),  # ~90km
    ]
    items = PlanningAgent._deterministic_selection(cands, 1, {"成都": (1, 1)})
    assert [it["name"] for it in items] == ["甲"]


def test_travel_legs_zero_for_colocated_sites():
    """共址点腿=0：不回归时长预算语义（180+180 恰满照放）。"""
    cands = [
        _cand("甲", "成都", suggested=180, loc=(104.06, 30.66)),
        _cand("乙", "成都", suggested=180, loc=(104.06, 30.66)),
    ]
    items = PlanningAgent._deterministic_selection(cands, 1, {"成都": (1, 1)})
    assert len(items) == 2


def test_far_pair_spreads_when_second_day_exists():
    """窗口两天时远距点不再挤同一天：走行腿把第二点推到次日（保不空天）。"""
    cands = [
        _cand("近甲", "成都", suggested=150, loc=(104.06, 30.66)),
        _cand("远乙", "成都", suggested=150, loc=(104.90, 31.20)),
        _cand("近丙", "成都", suggested=60, loc=(104.07, 30.67)),
    ]
    items = PlanningAgent._deterministic_selection(cands, 2, {"成都": (1, 2)})
    day_of = {it["name"]: it["day"] for it in items}
    assert day_of["近甲"] == day_of["近丙"]  # 同片同天
    assert day_of["远乙"] != day_of["近甲"]  # 跨城级远点分开


def test_must_visit_skips_full_and_transfer_days():
    """必去不再轮转乱放：满额天/转场日（360-180）让位给有余量的天。"""
    picked = [
        {
            "name": "满日点",
            "city": "成都",
            "category": "sight",
            "day": 1,
            "duration_minutes": 180,
        },
        {
            "name": "次日点",
            "city": "成都",
            "category": "sight",
            "day": 2,
            "duration_minutes": 120,
        },
    ]
    out = PlanningAgent._merge_must_visits(
        picked,
        ["新必去"],
        ["成都"],
        2,
        {"成都": (1, 2)},
        transfer_days={1},
    )
    must = next(s for s in out if s["name"] == "新必去")
    # day1 转场预算 180 已被占满 → 必去落 day2（120+60≤360）
    assert must["day"] == 2


def test_must_visit_never_dropped_when_all_days_full():
    """全窗满额：必去落最空天也不丢（用户点名愿超载是用户的决定）。"""
    picked = [
        {
            "name": "满甲",
            "city": "成都",
            "category": "sight",
            "day": 1,
            "duration_minutes": 360,
        },
        {
            "name": "半乙",
            "city": "成都",
            "category": "sight",
            "day": 2,
            "duration_minutes": 300,
        },
    ]
    out = PlanningAgent._merge_must_visits(
        picked, ["挤也要进"], ["成都"], 2, {"成都": (1, 2)}
    )
    must = next(s for s in out if s["name"] == "挤也要进")
    assert must["must"] is True
    assert must["day"] == 2  # 300 < 360 → 最空天


# --- 2026-10-31 地理放日 + 稀疏天回填 ---------------------------------------


def test_must_prefers_geo_near_day_over_earlier_far_day():
    """熊猫基地（北郊）不跟都江堰同天：有坐标必去优先落「距当日已放点
    ≤15km」的天，而不是最早有余量的天。"""
    # day2 已放：都江堰片区（~103.6, 30.9）；day3 已放：市中心两点
    picked = [
        {
            "name": "都江堰点",
            "city": "成都",
            "category": "sight",
            "day": 2,
            "duration_minutes": 180,
            "location": {"lon": 103.62, "lat": 30.90},
        },
        {
            "name": "市中心甲",
            "city": "成都",
            "category": "sight",
            "day": 3,
            "duration_minutes": 90,
            "location": {"lon": 104.06, "lat": 30.66},
        },
        {
            "name": "市中心乙",
            "city": "成都",
            "category": "sight",
            "day": 3,
            "duration_minutes": 90,
            "location": {"lon": 104.07, "lat": 30.67},
        },
    ]
    panda = {
        "name": "成都大熊猫繁育研究基地",
        "city": "成都",
        "category": "attraction",
        "location": {"lon": 104.15, "lat": 30.74},  # 北郊：市中心 ~10km、都江堰 ~50km
        "suggested_duration_min": 60,
    }
    out = PlanningAgent._merge_must_visits(
        picked, ["看熊猫"], ["成都"], 3, {"成都": (2, 3)}, bindings={"看熊猫": panda}
    )
    placed = next(s for s in out if s.get("must"))
    assert placed["day"] == 3  # 地理近距天，不是更早的都江堰天


def test_unlocated_must_goes_to_emptiest_day():
    """无坐标必去落最空天（不再 earliest-fit 堆进城窗口头一天）。"""
    picked = [
        {
            "name": "重日点",
            "city": "成都",
            "category": "sight",
            "day": 2,
            "duration_minutes": 300,
        },
        {
            "name": "轻日点",
            "city": "成都",
            "category": "sight",
            "day": 3,
            "duration_minutes": 90,
        },
    ]
    out = PlanningAgent._merge_must_visits(
        picked, ["无名占位"], ["成都"], 3, {"成都": (2, 3)}
    )
    must = next(s for s in out if s["name"] == "无名占位")
    assert must["day"] == 3  # 最空天（90 < 300）


def test_sparse_day_refills_from_beyond_pool():
    """池外候选回填稀疏天：跨区腿出局的大点不回填，同片区小点补进空天。"""
    g1 = (104.06, 30.66)  # 市中心
    g2 = (103.62, 30.90)  # 都江堰（远区）
    cands = [
        _cand("市1", "成都", suggested=180, loc=g1),
        _cand("市2", "成都", suggested=180, loc=g1),  # day1 360 满
        _cand("都1", "成都", suggested=90, loc=g2),
    ]
    cands += [
        _cand(f"远填{i}", "成都", suggested=180, loc=g1) for i in range(5)
    ]  # 池内：day2 90+180+120(跨区腿)=390 出局
    cands += [
        _cand(f"补{i}", "成都", suggested=60, loc=g2) for i in range(4)
    ]  # 池外同片区小点：回填 day2
    items = PlanningAgent._deterministic_selection(cands, 2, {"成都": (1, 2)})
    by_day = {}
    for it in items:
        by_day.setdefault(it["day"], []).append(it["name"])
    assert "都1" in by_day.get(2, [])
    refilled = [n for n in by_day.get(2, []) if n.startswith("补")]
    assert len(refilled) >= 2  # 稀疏天被池外同片区点回填
    assert not any(n.startswith("远填") for n in by_day.get(2, []))  # 跨区大点不硬塞


# --- 2026-10-31 打车出行模型：车程+半小时叫车 --------------------------------


def test_taxi_leg_model_drive_plus_hail():
    from app.services.agent.plan import (
        _TAXI_HAIL_MINUTES,
        _TAXI_MIN_PER_KM,
        _TRAVEL_LEG_CAP_MIN,
        _TRAVEL_MIN_PER_KM,
        _taxi_leg_min,
    )

    # 近距（≤1.5km）步行口径，不付叫车开销
    assert _taxi_leg_min(0.8) == round(0.8 * _TRAVEL_MIN_PER_KM)
    # 远距：车程（km×绕行/车速）+ 半小时叫车
    assert _taxi_leg_min(5.0) == round(5.0 * _TAXI_MIN_PER_KM) + _TAXI_HAIL_MINUTES
    assert _taxi_leg_min(50.0) == round(50.0 * _TAXI_MIN_PER_KM) + _TAXI_HAIL_MINUTES
    # 跨区一日游量级封顶
    assert _taxi_leg_min(300.0) == _TRAVEL_LEG_CAP_MIN


def test_taxi_model_allows_midrange_same_day():
    """10km 级市内点对按打车 ≈52 分钟计费：150+150+52 ≤ 360 同天可排
    （旧步行口径 10km≈162 分钟→封顶 120→420 出局）。"""
    a = _cand("甲", "成都", suggested=150, loc=(104.06, 30.66))
    b = _cand("乙", "成都", suggested=150, loc=(104.165, 30.66))  # ~10km
    items = PlanningAgent._deterministic_selection([a, b], 1, {"成都": (1, 1)})
    assert len(items) == 2
