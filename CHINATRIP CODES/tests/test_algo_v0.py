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

from app.services.agent.plan import DAY_VISIT_BUDGET_MINUTES, PlanningAgent
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
    # 2026-11-08 簇优先选日拍板「距离聚类优先/组合排日」（取代四拍
    # 「东方明珠要的」不追改口径）：人民广场三件 ≤1km 成族
    # （_FAMILY_ATOMIC_KM，11-08 深夜二拍收紧；含 tier2
    # 5A，族优先级最高）整族原子落 day1；陆家嘴三件族 day1 装不下
    # （4/日帽）整族落 day2——东方明珠不再以零散件身份挤进 day1 第
    # 4 席，同簇组合不拆天。锚随拍板反转，判例见
    # tests/test_cluster_first_days.py。
    assert by_day[1] == {
        "人民广场五A",
        "南京东路",
        "博物馆",
    }
    assert by_day[2] == {"东方明珠", "海洋馆", "滨江大道"}


# --- 每日时间预算与 4 个/日闸 -----------------------------------------------


def test_time_budget_soft_gate_overflows_not_drops():
    # 2026-11-02 拍板「时间约束是软闸不是硬闸」：180+180=360 满后
    # 第三个不再出局——软闸放行超额落位（4 个/日闸才是硬闸），
    # 物理可行性交求解层按真实时窗收口。
    cands = [
        _cand("甲", "成都", suggested=180, loc=(104.06, 30.66)),
        _cand("乙", "成都", suggested=180, loc=(104.06, 30.66)),
        _cand("丙", "成都", suggested=180, loc=(104.06, 30.66)),
    ]
    items = PlanningAgent._deterministic_selection(cands, 1, {"成都": (1, 1)})
    assert len(items) == 3


def test_four_per_day_cap():
    # 坐标错开 >1.5km（同点夹具互认会被伞名孪生吸收并卡绕开闸，须独立
    # 点验；族卡已废 10bd56b、贴邻同日圈 11-07 晚扩 5km——1.9km 错开
    # 在圈内，同日软偏好不破本测断言）。
    cands = [
        _cand(f"点{i}", "成都", suggested=30, loc=(104.06 + i * 0.02, 30.66))
        for i in range(6)
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
    # 优先级前置装满（4/日闸）：取代旧「最空天轮转均摊」——初排
    # 按池序前置，稀疏天由回填线 270'/LNS 兜底（2026-11-02 拍板链）。
    assert by_day[1] == {"成都景点00", "成都景点01", "成都景点02", "成都景点03"}
    assert by_day[2] == {"成都景点04", "成都景点05", "成都景点06", "成都景点07"}
    assert items[0]["city"] == "成都市"
    assert items[0]["duration_minutes"] == 60


def test_algo_respects_city_windows():
    cands = [_cand(f"渝{i}", "重庆") for i in range(4)]
    cands += [_cand(f"蓉{i}", "成都") for i in range(4)]
    items = PlanningAgent._deterministic_selection(
        cands, 4, {"成都": (1, 2), "重庆": (3, 4)}
    )
    days = {it["name"]: it["day"] for it in items}
    # 优先级前置装满但窗口合规（2026-11-02 拍板链）：4 件同窗城
    # 池序前置吃满窗口首日，不再强制均摊到窗口各天。
    assert sorted(d for n, d in days.items() if n.startswith("蓉")) == [1, 1, 1, 1]
    assert sorted(d for n, d in days.items() if n.startswith("渝")) == [3, 3, 3, 3]


# --- 演出 / 餐饮 / 夹紧 / 确定性 --------------------------------------------


def test_algo_show_closes_city_last_day_extra_show_takes_no_show_day():
    """2026-11-08 二拍「取消每城只自动排一场夜场」：头场演出守城市末日
    收尾，落选夜场逐张落位——一天一场仍守，第二场落无演出日（day3 已
    有演出；旧「落选即弃」语义由 b0a55e7 撤下，此锚改锁新拍板）。"""
    cands = [
        _cand("宽窄巷子", "成都"),
        _cand("变脸表演", "成都", cat="entertainment", suggested=105),
        _cand("蜀风雅韵", "成都", show=True),
        _cand("人民公园", "成都"),
    ]
    items = PlanningAgent._deterministic_selection(cands, 3, {"成都": (1, 3)})
    show = next(it for it in items if it["name"] == "变脸表演")
    assert show["day"] == 3  # 城市末日收尾
    assert show["duration_minutes"] == 105  # 库建议时长优先
    # ⑧二拍（2026-11-08）：取消「每城只排一场夜场」——落选场按聚簇/
    # 无演出日落位，一天一场仍守。蜀风雅韵无坐标走余量线，day2 空载承接。
    extra = next(it for it in items if it["name"] == "蜀风雅韵")
    assert extra["day"] == 2
    show_days = sorted(
        it["day"] for it in items if it["name"] in ("变脸表演", "蜀风雅韵")
    )
    assert show_days == [2, 3]  # 每天一场


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


def test_algo_show_avoids_return_day_when_evening_blocked():
    # 返程日晚上被 17 点档返程腿占住：夜场演出改钉前一天，不再与返程
    # 航班互斥搞垮整计划求解（2026-10-31 沪-西安-沪 5 天案：《梦回大唐》
    # 钉 day5 撞 17:00 航班 → day5 两卡 None 时间 + 全计划顺序兜底降级）
    cands = [
        _cand("景点A", "西安"),
        _cand("夜场秀", "西安", cat="entertainment"),
    ]
    items = PlanningAgent._deterministic_selection(
        cands, 5, {"西安": (1, 5), "上海": (5, 5)}, transfer_days={1, 5}
    )
    show = next(it for it in items if it["name"] == "夜场秀")
    assert show["day"] == 4  # 返程日(5)晚上有回程腿 → 钉前一天


def test_algo_show_stays_on_last_day_without_return_leg():
    # 末日无返程腿（transfer_days 不含总天数）：夜场照旧钉城市末日
    cands = [
        _cand("景点A", "成都"),
        _cand("变脸表演", "成都", cat="entertainment"),
    ]
    items = PlanningAgent._deterministic_selection(
        cands, 3, {"成都": (1, 3)}, transfer_days={1}
    )
    show = next(it for it in items if it["name"] == "变脸表演")
    assert show["day"] == 3


def test_show_day_budget_reserves_show_minutes():
    # 2026-11-04 拍板「360 不是硬闸不代表可以白天填满 360 再叠演出」
    # （西安 day4=360 POI+80 show=440 事故形态）：夜场演出钉日的参访
    # 预算=360-show_min——白天点给演出让位，装不下的溢出相邻天，
    # 演出日总参访不再超预算。
    cands = [
        _cand(f"点{i:02d}", "成都", suggested=90, loc=(104.06, 30.66))
        for i in range(14)
    ]
    cands.append(_cand("夜场秀", "成都", cat="entertainment"))
    items = PlanningAgent._deterministic_selection(
        cands, 5, {"成都": (1, 5)}, transfer_days={1, 5}
    )
    show = next(it for it in items if it["name"] == "夜场秀")
    assert show["day"] == 4  # 返程日(5)晚上有回程腿 → 钉前一天（既有语义）
    poi4 = [it for it in items if it["day"] == 4 and it["name"] != "夜场秀"]
    used = sum(it["duration_minutes"] for it in poi4) + show["duration_minutes"]
    assert used <= DAY_VISIT_BUDGET_MINUTES


def test_algo_show_adjacent_sight_co_schedules_with_pinned_show():
    # 2026-11-07 锦里古戏台/武侯祠案：仅夜场演出钉窗口末日、贴邻白天点
    # 却预占最早天——同街区一对被拆成首尾两天。近距同日圈（5km，
    # 11-07 晚拍板）内的候选认领序把演出日前置；圈外远点不受牵引
    # （软偏好只贴邻生效）。
    near = _cand("武侯祠", "成都", tags=["5a"], loc=(104.0493, 30.6445))
    far = _cand("远郊雪山大点", "成都", tags=["5a"], loc=(102.92, 31.13))
    cands = [
        near,
        far,
        _cand("锦里古戏台", "成都", cat="entertainment", loc=(104.0588, 30.6502)),
    ]
    items = PlanningAgent._deterministic_selection(cands, 3, {"成都": (1, 3)})
    day = {it["name"]: it["day"] for it in items}
    assert day["锦里古戏台"] == 3  # 城市末日收尾（既有语义）
    assert day["武侯祠"] == 3  # 贴邻演出 → 同日连排（白天看祠晚上看戏）
    assert day["远郊雪山大点"] == 1  # 圈外不被牵引，照旧预占最早天


def test_algo_merge_binding_beats_fuzzy_pool_card():
    # 2026-11-07 锦里古戏台/武侯祠案：心愿词「锦里」复合挂牌通道把
    # 两条愿望全吸到同一张「武侯祠·锦里」池卡（_name_dup 双双命中），
    # 卡被去重并掉后必去静默蒸发。绑定真身在手时模糊池卡不冒充必去
    # ——绕过 match 走绑定分支，真身卡强制进排期。
    picked = [
        {"name": "武侯祠·锦里", "city": "成都", "day": 2, "duration_minutes": 90},
        {"name": "锦里古街", "city": "成都", "day": 2, "duration_minutes": 90},
    ]
    bindings = {
        "武侯祠": {
            "name": "成都武侯祠博物馆",
            "city": "成都",
            "location": {"lon": 104.04932, "lat": 30.644529},
        },
        "锦里古戏台": {
            "name": "锦里古戏台",
            "city": "成都",
            "location": {"lon": 104.0588, "lat": 30.6502},
        },
    }
    out = PlanningAgent._merge_must_visits(
        picked,
        ["武侯祠", "锦里古戏台"],
        ["成都"],
        3,
        {"成都": (1, 3)},
        bindings=bindings,
    )
    names = {s["name"]: s for s in out}
    assert "成都武侯祠博物馆" in names and names["成都武侯祠博物馆"]["must"]
    assert "锦里古戏台" in names and names["锦里古戏台"]["must"]
    # 池卡不再冒充必去（没有绑定真身等名时不标）
    assert not names["武侯祠·锦里"].get("must")


def test_algo_dedup_never_drops_must_card_for_pool_twin():
    # 2026-11-07 同案去重侧：必去卡在同站孪生合并中永不让位（铁律
    # 19）——池卡先入列也不能把必去卡吃掉。
    from app.services.agent.plan import _dedupe_visit_keepers

    pool_card = VisitItem(
        item_id="v1",
        name="武侯祠·锦里",
        poi_id="st_db921a769059",
        city="成都",
        day=3,
    )
    must_card = VisitItem(
        item_id="v2",
        name="锦里古戏台",
        poi_id="ct_成都_309",
        city="成都",
        day=3,
        must=True,
    )
    keepers, dropped = _dedupe_visit_keepers([pool_card, must_card])
    assert [k.name for k in keepers] == ["锦里古戏台"]
    assert dropped == ["武侯祠·锦里"]


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
    # 2026-11-02 软闸拍板：转场日扣减 180 不再决定出局（三个全放），
    # 只影响溢出目标天选择——见 test_transfer_days_only_deduct_listed_days。
    assert len(pinned) == 3


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


def test_travel_legs_count_but_soft_gate_keeps_far_pair():
    """走行腿仍计入当日载荷（影响落日与溢出目标天，见
    test_far_pair_spreads_when_second_day_exists）；2026-11-02 软闸
    拍板后 150+150+腿>360 不再出局——超额照排，物理可行性交求解层。
    """
    cands = [
        _cand("甲", "成都", suggested=150, loc=(104.06, 30.66)),
        _cand("乙", "成都", suggested=150, loc=(104.90, 31.20)),  # ~90km
    ]
    items = PlanningAgent._deterministic_selection(cands, 1, {"成都": (1, 1)})
    assert [it["name"] for it in items] == ["甲", "乙"]


def test_soft_gate_rejects_cross_city_far_leg():
    """软超额远腿闸（2026-11-04 成渝案）：>150km 直线距的腿不做软超额
    ——四面山+白帝城 ~330km 同天只排一个，交回填/披露。分钟口径被
    TRAVEL_LEG_CAP_MIN 封顶（90km 与 330km 同值 180），闸必须用公里。"""
    cands = [
        _cand("四面山", "重庆", suggested=240, loc=(106.42, 29.22)),
        _cand("白帝城", "重庆", suggested=240, loc=(109.57, 31.05)),  # ~330km
    ]
    items = PlanningAgent._deterministic_selection(cands, 1, {"重庆": (1, 1)})
    assert len(items) == 1


def test_pool_twin_collapse_keeps_premium_survivor():
    """同站孪生并卡保留名录王牌（2026-11-04 成渝案）：大足石刻 unesco
    行 category 空、pref 无从评起——无品类王牌按偏好命中算（_pref_key），
    tier 梯子把 unesco 行顶回队首，并卡卡名回归 石刻 本体而非博物馆。"""
    mus = _cand("大足石刻博物馆", "重庆", suggested=120, tags=["历史文化"])
    mus["source"] = "museum1"
    grotto = _cand("大足石刻", "重庆", cat="", suggested=300, tags=["unesco"])
    grotto["source"] = "unesco"
    items = PlanningAgent._deterministic_selection(
        [mus, grotto], 1, {"重庆": (1, 1)}, preferences="历史文化"
    )
    assert [it["name"] for it in items] == ["大足石刻"]


def test_pool_twin_collapse_survivor_not_pool_order_dependent():
    """并卡幸存者与池序无关（2026-11-04 成渝案二段）：真实管线投影把
    无品类行默认成 sight（plan.py 候选投影 category or "sight"），石刻
    偏好豁免失效、museum1 行反超池首——旧版池序首位当幸存者会留下
    博物馆行、把 unesco 本体并入。组内 (tier, idx) 挑幸存者后不再如此。"""
    mus = _cand("大足石刻博物馆", "重庆", suggested=120, tags=["历史文化"])
    mus["source"] = "museum1"
    grotto = _cand("大足石刻", "重庆", cat="sight", suggested=300, tags=["unesco"])
    grotto["source"] = "unesco"
    items = PlanningAgent._deterministic_selection(
        [grotto, mus], 1, {"重庆": (1, 1)}, preferences="历史文化"
    )
    assert [it["name"] for it in items] == ["大足石刻"]


def test_pool_cap_never_evicts_premium_tier():
    """池上限不逐名录王牌（2026-11-04 成渝案二段）：投影把无品类行默认
    成 sight 后偏好豁免失效，博物馆密集池（真偏好命中）把 unesco 石刻
    挤出 span*4 席——tier≤2 行必须追回池内，交后续时序闸/白名单披露，
    不得静默出局。"""
    cands = []
    for i in range(16):
        m = _cand(f"博物馆{i}", "重庆", suggested=90, tags=["历史文化"])
        m["source"] = "museum1"
        m["rating"] = 4.8
        m["category"] = "museum"
        cands.append(m)
    grotto = _cand("大足石刻", "重庆", cat="sight", suggested=300, tags=["unesco"])
    grotto["source"] = "unesco"
    grotto["rating"] = 4.6
    cands.append(grotto)
    items = PlanningAgent._deterministic_selection(
        cands, 4, {"重庆": (1, 4)}, preferences="历史文化"
    )
    assert any(it["name"] == "大足石刻" for it in items)


def test_pool_cap_never_evicts_high_quality_sights():
    """池上限不逐高质名点（2026-11-05 成都名点案）：tier 梯子把名录档
    排前，quality≥4.5 的图商名点（宽窄巷子/熊猫基地/洛带/东郊记忆，
    rating 4.6 无 count）被切在 span*4 池外；回填线对池外尾巴是硬预算
    +腿费，180 分钟级大点塞不进半满日——高质名点必须与 tier≤2 同权
    追回池内（软闸语义同池内正选点），否则 4 天窗口只排 5 件、日预算
    50-60%。无评分长尾不享此权（池外硬闸口径不变）。"""
    downtown = (104.06, 30.66)
    cands = []
    # 8 行 nature 类（品类闸 cap=2 会裁 6）+ 12 行 attraction：
    # tier10 共 20 行占满池上限 16 席，名点被切池外
    for i in range(8):
        c = _cand(f"山{i}", "成都", cat="nature", suggested=90, loc=downtown)
        c["source"] = "4a"
        cands.append(c)
    for i in range(12):
        c = _cand(f"市{i}", "成都", cat="attraction", suggested=90, loc=downtown)
        c["source"] = "4a"
        cands.append(c)
    # 池外高质名点：180 分钟大点 + ~60km 远腿（硬回填 180+腿费>日预算余量）
    for i in range(2):
        c = _cand(
            f"名点{i}", "成都", cat="attraction", suggested=180, loc=(103.6, 30.9)
        )
        c["source"] = "amap"  # tier 11
        c["rating"] = 4.6
        cands.append(c)
    # 对照：无评分长尾同规格 → 不追回、硬回填也塞不进（坐标与名点
    # 错开 >1km——2026-11-07 并卡拍板后同点行会以族件身份搭车进卡，
    # 就验不出「quality=0 不享追回权」了）
    tail = _cand("长尾", "成都", cat="attraction", suggested=180, loc=(103.6, 30.75))
    tail["source"] = "amap"
    cands.append(tail)
    items = PlanningAgent._deterministic_selection(cands, 4, {"成都": (1, 4)})
    names = {it["name"] for it in items}
    assert {"名点0", "名点1"} <= names  # 高质名点追回并落位（软闸）
    assert "长尾" not in names  # quality=0 不享追回权


def test_baidu_rating_normalized_against_amap():
    """评分跨源不可比（2026-11-07 用户拍板）：rating_source='baidu' 行
    质量分 ×0.9——同档内百度虚高 5.0 不得反超高德 4.6 名录地标（农科村
    vs 武侯祠案）。1 天 4 席满池：amap 名点必须进池，baidu 5.0 让位。"""
    # 坐标错开 ~1.9km（2026-11-07 并卡拍板：0.01°≈0.96km 的链会互认
    # 同街族、族件豁免 4/日计数，4 席变 5 件——验池席位须独立点）。
    cands = [
        _cand(
            f"农科村{i}",
            "成都",
            cat="attraction",
            suggested=90,
            loc=(103.6 + i * 0.02, 30.9),
        )
        for i in range(4)
    ]
    for i, c in enumerate(cands):
        c["source"] = "baidu"
        c["rating"] = 5.0
        c["rating_source"] = "baidu"
    amap = _cand("武侯祠", "成都", cat="attraction", suggested=90, loc=(104.05, 30.65))
    amap["source"] = "amap"
    amap["rating"] = 4.6
    amap["rating_source"] = "amap"
    cands.append(amap)
    items = PlanningAgent._deterministic_selection(cands, 1, {"成都": (1, 1)})
    names = {it["name"] for it in items}
    assert "武侯祠" in names  # amap 4.6 > baidu 5.0×0.9=4.5，进池且占席
    assert len(names) == 4  # 1 天 4 席：恰好一个 baidu 行被挤出局
    assert sum(1 for n in names if n.startswith("农科村")) == 3


def test_preclaim_far_guard_spreads_premium_pair():
    """预占位严格位同样不并互远大点（2026-11-04 成渝案二段）：石刻
    300min 与金佛山 180min 互相 >150km，腿分钟被 TRAVEL_LEG_CAP_MIN
    封顶 180 让两条远腿在预算口径里同值，双双过闸挤同一天 → 求解层
    300min 大点排不出时刻被清算移除。严格位必须与软闸/主环同口径
    （_SOFT_FAR_KM 公里闸）。"""
    a = _cand("大足石刻", "重庆", suggested=300, loc=(105.70, 29.71))
    a["source"] = "unesco"
    a["tags"] = ["unesco"]
    a["rating"] = 4.6
    b = _cand("金佛山", "重庆", suggested=180, loc=(107.18, 29.02))
    b["source"] = "5a"
    b["tags"] = ["5a"]
    b["rating"] = 4.5
    items = PlanningAgent._deterministic_selection([a, b], 2, {"重庆": (1, 2)})
    day_of = {it["name"]: it["day"] for it in items}
    assert day_of["大足石刻"] != day_of["金佛山"]


def test_host_day_for_visit_rejects_far_conflict():
    """挪日宿主闸（2026-11-04 成渝案三段）：_host_day_for_visit 收到
    incoming 远点时不得收进已有 >150km 互远参访的天——否则求解层
    把选点层已分好天的石刻/金佛山重撞同日，兜底 sequencing 排不出
    时刻整卡蒸发。宿主资格看公里不看分钟（腿封顶 180 让预算闸对
    90km/330km 同值）。"""
    from app.services.agent.plan import _far_conflict_items, _host_day_for_visit
    from app.services.itinerary.models import DayPlan, GeoPoint

    jfs = VisitItem(
        item_id="t1",
        name="金佛山",
        category="sight",
        city="重庆",
        location=GeoPoint(lon=107.18, lat=29.02),
        day=1,
        duration_minutes=180,
    )
    far_day = DayPlan(day=1, base_city="重庆", items=[jfs])
    empty_day = DayPlan(day=2, base_city="重庆", items=[])
    stone = GeoPoint(lon=105.70, lat=29.71)  # 大足石刻，与金佛山 ~159km

    assert _far_conflict_items([jfs], stone)
    assert not _far_conflict_items([jfs])  # 单点无对

    host = _host_day_for_visit([far_day, empty_day], "重庆", 300, incoming=stone)
    assert host is not None and host.day == 2

    # 近点不受闸：金佛山旁的小点仍可进 day1（非一刀切拒收）
    near = GeoPoint(lon=107.20, lat=29.05)
    assert (
        _host_day_for_visit([far_day, empty_day], "重庆", 60, incoming=near) is far_day
    )


def test_pref_band_keeps_premium_far_pair_apart():
    """偏好带不拆远点对（2026-11-04 成渝案三段）：偏好「自然风光」让
    nature 行预占位排到池首，石刻排队垫底，全窗被远腿闸拒收后走主环
    簇日直排（旧代码直排无远腿闸）与金佛山同日。预占位认领序须给
    名录王牌次级先认领（物理受限 > 王牌 > 偏好带）——同日列表序仍按
    池序（装配尾部重排），「偏好位在 tier 之前」拍板不破。"""
    stone = _cand("大足石刻", "重庆", suggested=300, loc=(105.70, 29.71))
    stone["source"] = "unesco"
    stone["tags"] = ["unesco"]
    stone["rating"] = 4.6
    stone["category"] = "sight"  # 组装层投影 `or "sight"` 后的形态
    jfs = _cand("金佛山风景名胜区", "重庆", suggested=180, loc=(107.18, 29.02))
    jfs["source"] = "scenic"
    jfs["tags"] = ["5a"]
    jfs["rating"] = 4.5
    jfs["category"] = "nature"  # 偏好「自然风光」命中
    items = PlanningAgent._deterministic_selection(
        [stone, jfs], 2, {"重庆": (1, 2)}, preferences="历史文化 自然风光"
    )
    day_of = {it["name"]: it["day"] for it in items}
    assert day_of.get("大足石刻") is not None
    assert day_of.get("金佛山风景名胜区") is not None
    assert day_of["大足石刻"] != day_of["金佛山风景名胜区"]


def test_rehome_untimed_visits_moves_far_stray():
    """全日挪日扫尾（2026-11-04 成渝案四段）：非转场日无时刻卡此前
    只有终局清算一途——CP 分钟口径把石刻与金佛山装进同一天后，石刻
    排不出时刻直接蒸发。清算前须先试挪日（互远闸同款口径），挪到
    有容量且不互远的天重排；全窗不互远的天都没有才留原天交清算。"""
    from datetime import time as _time

    from app.services.agent.plan import _rehome_untimed_visits
    from app.services.itinerary.models import DayPlan, GeoPoint, ItineraryPlan

    def _vis(name, day, *, timed, dur, lon, lat):
        return VisitItem(
            item_id=f"v_{name}",
            name=name,
            category="sight",
            city="重庆",
            location=GeoPoint(lon=lon, lat=lat),
            day=day,
            start_time=_time(9, 0) if timed else None,
            end_time=_time(12, 0) if timed else None,
            duration_minutes=dur,
        )

    plan = ItineraryPlan(
        itinerary_id="t",
        cities=["重庆"],
        days=[
            DayPlan(
                day=1,
                base_city="重庆",
                items=[
                    _vis("金佛山", 1, timed=True, dur=180, lon=107.18, lat=29.02),
                    _vis("大足石刻", 1, timed=False, dur=300, lon=105.70, lat=29.71),
                ],
            ),
            DayPlan(day=2, base_city="重庆", items=[]),
        ],
    )
    notes = _rehome_untimed_visits(plan)
    stone = next(
        i for d in plan.days for i in d.items if getattr(i, "name", "") == "大足石刻"
    )
    assert stone.day == 2
    assert notes and "挪至第2天" in notes[0]

    # 全窗互远：无天可挪 → 留原天交清算披露
    plan2 = ItineraryPlan(
        itinerary_id="t2",
        cities=["重庆"],
        days=[
            DayPlan(
                day=1,
                base_city="重庆",
                items=[
                    _vis("金佛山", 1, timed=True, dur=180, lon=107.18, lat=29.02),
                    _vis("大足石刻", 1, timed=False, dur=300, lon=105.70, lat=29.71),
                ],
            ),
            DayPlan(
                day=2,
                base_city="重庆",
                items=[
                    _vis("濯水景区", 2, timed=True, dur=240, lon=108.78, lat=29.53),
                ],
            ),
        ],
    )
    assert _rehome_untimed_visits(plan2) == []
    stone2 = next(
        i for d in plan2.days for i in d.items if getattr(i, "name", "") == "大足石刻"
    )
    assert stone2.day == 1


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


def test_soft_gate_shape_and_beyond_pool_tail_stays_hard():
    """2026-11-02 软闸拍板后的形态锁定（原「稀疏天回填」语义被软闸
    取代）：同档短时长先占位（补0-3 先入池占 day1，恰 4 个/日闸
    封顶）；池内正选大点（市1/市2/远填0）预算外软闸超额落位 day2；
    池外尾巴（远填1-4）不享软闸——时间闸照硬，不硬塞。"""
    g1 = (104.06, 30.66)  # 市中心
    g2 = (103.62, 30.90)  # 都江堰（远区）
    cands = [
        _cand("市1", "成都", suggested=180, loc=g1),
        _cand("市2", "成都", suggested=180, loc=g1),  # day1 360 满
        _cand("都1", "成都", suggested=90, loc=g2),
    ]
    # 远填坐标彼此错开 >1.5km（互不粘连；贴邻同日圈已扩 5km，1.9km
    # 错开在圈内——同日软偏好与断言 day2 同向，池外硬闸不变）。
    cands += [
        _cand(f"远填{i}", "成都", suggested=180, loc=(104.06 + (i + 1) * 0.02, 30.66))
        for i in range(5)
    ]
    cands += [_cand(f"补{i}", "成都", suggested=60, loc=g2) for i in range(4)]
    items = PlanningAgent._deterministic_selection(cands, 2, {"成都": (1, 2)})
    by_day = {}
    for it in items:
        by_day.setdefault(it["day"], []).append(it["name"])
    # day1=池内短时长小点 ×4（同档短时长先占位，恰 4 个/日闸封顶；
    # 2026-11-07 反转拍板：无族豁免，都1 照占计数溢出 day2）；
    # day2=软闸超额大点卡（市1+市2 同点）+溢出的远填0+都1。
    assert sorted(by_day.get(1, [])) == ["补0", "补1", "补2", "补3"]
    assert sorted(by_day.get(2, [])) == ["市1", "市2", "远填0", "都1"]
    # 池外尾巴不硬塞：远填1-4 不入任何天（软闸只保池内正选点）
    flat = [n for names in by_day.values() for n in names]
    assert not any(n in flat for n in ("远填1", "远填2", "远填3", "远填4"))


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


def test_fallback_shifts_lunch_for_oversize_morning_visit():
    # 2026-11-03 拍板：开餐硬窗 [11:30, 12:30]——240 分钟大点 09:00-13:00
    # 整段压窗时不再无界顺延（旧版可滑到 20:00「8pm 午餐」事故），当天
    # 移除午餐（铁律 20 同义：过午不强插）
    from datetime import time as _t

    from app.services.agent.plan import _fallback_sequence_times
    from app.services.itinerary.models import DayPlan, ItineraryPlan, VisitItem

    # 系统午餐占位带 soft_pin=True（2026-10-31 软钉语义：兜底/求解器只
    # 顺延系统钉；用户手钉 pinned=True 且 soft_pin=False 纹丝不动=铁律19）
    lunch = VisitItem(
        item_id="l1",
        name="午饭",
        city="北京",
        day=1,
        category="food",
        duration_minutes=60,
        start_time=_t(12, 0),
        end_time=_t(13, 0),
        pinned=True,
        soft_pin=True,
    )
    big = VisitItem(
        item_id="v1",
        name="大点",
        city="北京",
        day=1,
        duration_minutes=240,
    )
    plan = ItineraryPlan(
        itinerary_id="it-x",
        cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=[lunch, big])],
        assumptions=[],
    )
    _fallback_sequence_times(plan)
    assert big.start_time is not None and big.start_time.hour == 9
    assert big.end_time is not None and big.end_time.hour == 13
    # 午餐硬窗 [11:30, 12:30] 被大点整段压满：移除（不插 8pm 午餐）
    assert lunch not in plan.days[0].items


def _mini_plan_with_lunch(lunch_start, show=None, visit_dur=120):
    from datetime import time as _t

    from app.services.itinerary.models import DayPlan, ItineraryPlan, VisitItem

    items = [
        VisitItem(
            item_id="l1",
            name="午饭",
            city="北京",
            day=1,
            category="food",
            duration_minutes=60,
            start_time=lunch_start,
            end_time=_t(lunch_start.hour, lunch_start.minute + 60)
            if lunch_start.minute + 60 < 60
            else _t(lunch_start.hour + 1, (lunch_start.minute + 60) % 60),
            pinned=True,
            soft_pin=True,
        ),
        VisitItem(
            item_id="v1", name="大点", city="北京", day=1, duration_minutes=visit_dur
        ),
    ]
    if show is not None:
        st, en = show
        items.append(
            VisitItem(
                item_id="s1",
                name="场次点",
                city="北京",
                day=1,
                best_visit_time="show",
                start_time=st,
                end_time=en,
                duration_minutes=(en.hour * 60 + en.minute)
                - (st.hour * 60 + st.minute),
                pinned=True,
            )
        )
    return ItineraryPlan(
        itinerary_id="it-x",
        cities=["北京"],
        days=[DayPlan(day=1, base_city="北京", items=items)],
        assumptions=[],
    )


def test_fallback_lunch_moves_earlier_within_30min():
    # 2026-11-01 用户拍板：午餐可提前半小时——12:30 固定场次前，午餐
    # 12:00 提前到 11:30（全时长）落位，不再挡上午。
    from datetime import time as _t

    from app.services.agent.plan import _fallback_sequence_times

    plan = _mini_plan_with_lunch(_t(12, 0), show=(_t(12, 30), _t(13, 30)))
    _fallback_sequence_times(plan)
    lunch = next(v for v in plan.days[0].items if v.item_id == "l1")
    visit = next(v for v in plan.days[0].items if v.item_id == "v1")
    assert visit.start_time == _t(9, 0)
    assert lunch.start_time == _t(11, 30)  # 提前 30 分钟
    assert lunch.end_time == _t(12, 30)  # 全时长 60 分钟


def test_fallback_lunch_earlier_and_shortened_30min():
    # 2026-11-03 拍板：开餐硬窗 [11:30, 12:30] + 极端可缩 30 分钟——
    # 12:15 固定场次挤不下全时长，午餐提前到 11:30 并缩短为 30 分钟。
    from datetime import time as _t

    from app.services.agent.plan import _fallback_sequence_times

    plan = _mini_plan_with_lunch(_t(12, 0), show=(_t(12, 15), _t(13, 15)))
    _fallback_sequence_times(plan)
    lunch = next(v for v in plan.days[0].items if v.item_id == "l1")
    visit = next(v for v in plan.days[0].items if v.item_id == "v1")
    assert visit.start_time == _t(9, 0)
    assert lunch.start_time == _t(11, 30)  # 提前 30 分钟
    assert lunch.end_time == _t(12, 0)  # 缩短为 30 分钟
    assert lunch.duration_minutes == 30


def test_fallback_evening_item_not_in_daytime():
    # 2026-11-01「两江夜游排在白天」事故：降级兜底同步 solver 时段窗下
    # 限——evening 17:00 起、sunset 16:00 起，非演出夜间点不进白天。
    from datetime import time as _t

    from app.services.agent.plan import _fallback_sequence_times
    from app.services.itinerary.models import DayPlan, ItineraryPlan, VisitItem

    cruise = VisitItem(
        item_id="v1",
        name="两江夜游",
        city="重庆",
        day=1,
        category="attraction",
        best_visit_time="evening",
        duration_minutes=90,
    )
    deck = VisitItem(
        item_id="v2",
        name="南山一棵树观景台",
        city="重庆",
        day=1,
        best_visit_time="sunset",
        duration_minutes=60,
    )
    plan = ItineraryPlan(
        itinerary_id="it-nc",
        cities=["重庆"],
        days=[DayPlan(day=1, base_city="重庆", items=[cruise, deck])],
        assumptions=[],
    )
    _fallback_sequence_times(plan)
    assert cruise.start_time is not None and cruise.start_time >= _t(17, 0)
    assert deck.start_time is not None and deck.start_time >= _t(16, 0)


def test_sched_best_visit_fills_missing_signal_by_name():
    # 2026-11-01 事故根因：intl 骨架行 best_visit_time 停在列默认 any。
    # 规整层只在缺信号时按名称规则兜底（与回填作业同源）；已有非 any 值
    # 原样透传（只升不降），住宿类不参访排程。
    from app.services.agent.plan import _sched_best_visit

    # 缺信号 + 夜游名 → evening
    assert (
        _sched_best_visit({"name": "两江夜游", "best_visit_time": "any"}) == "evening"
    )
    assert _sched_best_visit({"name": "两江夜游", "best_visit_time": None}) == "evening"
    assert _sched_best_visit({"name": "较场口夜市"}) == "evening"
    assert _sched_best_visit({"name": "南山一棵树观景台"}) == "sunset"
    # 已有非 any 值原样透传，绝不被名称规则覆盖
    assert _sched_best_visit({"name": "两江夜游", "best_visit_time": "show"}) == "show"
    assert (
        _sched_best_visit({"name": "磁器口古镇", "best_visit_time": "morning"})
        == "morning"
    )
    # 住宿类（名称/类别任一命中）直接透传原值
    assert (
        _sched_best_visit({"name": "雅致酒店(珠江夜游店)", "category": "hotel"}) is None
    )
    # 无信号无夜名 → 原样 any
    assert _sched_best_visit({"name": "磁器口古镇", "best_visit_time": "any"}) == "any"
    assert _sched_best_visit(None) is None
