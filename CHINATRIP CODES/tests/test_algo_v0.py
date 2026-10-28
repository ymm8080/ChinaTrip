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
