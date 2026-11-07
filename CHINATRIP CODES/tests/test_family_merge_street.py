"""同街族并卡（2026-11-07 拍板三件套）：

① 直线 ≤1km 的同日站点折进首件主卡（stops chips），>1km 保持多卡；
② 族卡停留时长取族内最长一站，不是求和；
③ 选层账本族口径：子站不计 4 个/日闸、预算只收族边际
   （max(0, 时长−族内当前最大)），紧预算日不因并卡把整族挤掉；
④ 心愿覆盖认子站：心愿名/绑定号落在子站 chip 上 = 已在册，
   不回炉重排（_sync_wish_rows 同口径）。
"""

from __future__ import annotations

import asyncio

from app.services.agent.plan import PlanningAgent, PlanSession
from app.services.itinerary import VisitItem
from app.services.llm.base import ChatResult

# 西安钟楼簇（约 114.0, 34.0）与远点（约 14km 外）
_ZL = (114.0, 34.0)
_FAR = (114.15, 34.0)


def _loc(xy: tuple[float, float]) -> dict:
    return {"lon": xy[0], "lat": xy[1]}


class BoomLLM:
    async def chat(self, messages, *, temperature=0.3, max_tokens=None) -> ChatResult:
        raise AssertionError("these tests must not call the LLM")


class BoomSearch:
    """无检索依赖——心愿覆盖若误判回炉会撞这里。"""

    def search(self, *a, **k):  # pragma: no cover - 断言路径
        raise AssertionError("covered wish must not re-enter the must pipeline")


def _picked(name, loc, minutes, *, must=False):
    return {
        "name": name,
        "city": "西安",
        "day": 1,
        "duration_minutes": minutes,
        "category": "sight",
        "location": _loc(loc),
        "must": must,
    }


def _cand(name, loc, poi_id, en):
    return {
        "name": name,
        "city": "西安",
        "category": "sight",
        "source_poi_id": poi_id,
        "name_en": en,
        "location": _loc(loc),
    }


# --- ② 装配：≤1km 族并一卡 + 时长取 max；>1km 保持多卡 -----------------------


def _family_plan(picked, cands):
    agent = PlanningAgent(BoomLLM(), auto_restaurants=False)
    assumptions: list = []
    plan = asyncio.run(
        agent._assemble_plan(
            ["西安"], 1, picked, cands, assumptions, start_date="2026-11-16"
        )
    )
    return agent, plan, assumptions


def test_assembly_merges_family_and_takes_max_duration():
    picked = [
        _picked("西安钟楼", _ZL, 60),
        _picked("西安鼓楼", (_ZL[0] + 0.005, _ZL[1]), 90),
        _picked("大雁塔", _FAR, 120),
    ]
    cands = [
        _cand("西安钟楼", _ZL, "p-zl", "Bell Tower"),
        _cand("西安鼓楼", (_ZL[0] + 0.005, _ZL[1]), "p-gl", "Drum Tower"),
        _cand("大雁塔", _FAR, "p-dyt", "Giant Wild Goose Pagoda"),
    ]
    agent, plan, assumptions = _family_plan(picked, cands)
    day1 = [v for v in plan.days[0].items if isinstance(v, VisitItem)]
    sights = [v for v in day1 if v.category not in ("food", "hotel")]
    assert {v.name for v in sights} == {"西安钟楼", "大雁塔"}
    card = next(v for v in sights if v.name == "西安钟楼")
    # 时长取族内最长（90），不是求和（60+90=150）
    assert card.duration_minutes == 90
    assert [s.name for s in card.stops] == ["西安鼓楼"]
    assert card.stops[0].poi_id == "p-gl"
    assert card.stops[0].name_en == "Drum Tower"
    # 假设区披露并卡事实
    assert any("同街" in a for a in assumptions)


def test_far_member_stays_separate_card_same_day():
    picked = [
        _picked("西安钟楼", _ZL, 60),
        _picked("远点", _FAR, 60),
    ]
    cands = [
        _cand("西安钟楼", _ZL, "p-zl", "Bell Tower"),
        _cand("远点", _FAR, "p-far", "Far"),
    ]
    _, plan, _ = _family_plan(picked, cands)
    sights = [
        v
        for v in plan.days[0].items
        if isinstance(v, VisitItem) and v.category not in ("food", "hotel")
    ]
    assert len(sights) == 2
    card = next(v for v in sights if v.name == "西安钟楼")
    assert card.stops is None


def test_must_flag_propagates_and_protect_names_expand():
    picked = [
        _picked("西安钟楼", _ZL, 60),
        _picked("西安鼓楼", (_ZL[0] + 0.005, _ZL[1]), 90, must=True),
    ]
    cands = [
        _cand("西安钟楼", _ZL, "p-zl", "Bell Tower"),
        _cand("西安鼓楼", (_ZL[0] + 0.005, _ZL[1]), "p-gl", "Drum Tower"),
    ]
    agent, plan, _ = _family_plan(picked, cands)
    card = next(
        v
        for v in plan.days[0].items
        if isinstance(v, VisitItem) and v.name == "西安钟楼"
    )
    # 子站必去 → 必去标随主卡，protect 名册经 _family_must_names 扩到卡名
    assert card.must is True
    assert agent._family_must_names({"西安鼓楼"}) == {"西安鼓楼", "西安钟楼"}


def test_entertainment_member_joins_family_card():
    # 2026-11-07 二拍「所有距离近的都可以并族」：演出/街区型不再豁免。
    # 大雁塔锚卡收编 0.77km 外的长安十二时辰街区块，时长=族内 max(240)。
    picked = [
        _picked("大雁塔大唐芙蓉园景区", _ZL, 180),
        {
            **_picked("长安十二时辰主题街区", (_ZL[0] + 0.008, _ZL[1]), 240),
            "category": "entertainment",
        },
    ]
    cands = [
        _cand("大雁塔大唐芙蓉园景区", _ZL, "p-dyt", "Dayanta"),
        _cand(
            "长安十二时辰主题街区",
            (_ZL[0] + 0.008, _ZL[1]),
            "p-sec",
            "Twelve Hours Block",
        ),
    ]
    agent, plan, assumptions = _family_plan(picked, cands)
    sights = [
        v
        for v in plan.days[0].items
        if isinstance(v, VisitItem) and v.category not in ("food", "hotel")
    ]
    assert {v.name for v in sights} == {"大雁塔大唐芙蓉园景区"}
    card = sights[0]
    assert card.duration_minutes == 240
    assert [s.name for s in card.stops] == ["长安十二时辰主题街区"]
    assert any("同街" in a for a in assumptions)
    assert agent._family_must_names({"长安十二时辰主题街区"}) == {
        "长安十二时辰主题街区",
        "大雁塔大唐芙蓉园景区",
    }


# --- ③ 选层：族边际预算——紧预算日成员跟锚走，不被全额挤去别天 ---------------


def test_selection_family_marginal_keeps_member_with_anchor():
    # 摆位（西安本地 km，lat34：1°lat≈111.2km、1°lon≈92.3km）：
    #   远一 1.8km N、远二 2.4km E、钟楼原点、鼓楼A 0.46km E（族内）、
    #   鼓楼B 2.3km SW（族外；>1.5km 不触发贴邻 hoist，且与钟楼/远一的
    #   距离不与 1.8km 打平——聚类种子就近归属无歧义）。
    # 聚类 k=2：种子=远一、最远点=鼓楼B → 簇{远一,远二,钟楼,鼓楼A}=day1、
    # 簇{鼓楼B}=day2。day1 账：远一 60 + 远二 97 + 钟楼 154 = 311 ≤ 360；
    # 鼓楼A 族边际 max(0,90−120)=0 + 步行腿 7 → 318 ≤ 360 与锚同日
    # （sum 语义全额 90+7=97 → 408 > 360 → 被挤去 day2=拆族）。
    # 鼓楼B 对照（无族口径）：90 落 day2，与钟楼不同日。
    near = (_ZL[0] + 0.005, _ZL[1])  # ~0.46km，族内
    away = (_ZL[0] - 0.017624, _ZL[1] - 0.014624)  # ~2.3km SW，族外
    far1 = (_ZL[0], _ZL[1] + 0.016185)  # ~1.8km N
    far2 = (_ZL[0] + 0.026012, _ZL[1])  # ~2.4km E
    base = [
        _cand("远一", far1, "p-f1", "Far1"),
        _cand("远二", far2, "p-f2", "Far2"),
        _cand("钟楼", _ZL, "p-zl", "Bell"),
    ]
    drum_near = _cand("鼓楼", near, "p-gl", "Drum")
    drum_away = _cand("鼓楼", away, "p-gl", "Drum")
    # 选层读 suggested_duration_min（_cand 不带时长的兜底 60 不够压预算）
    base[0]["suggested_duration_min"] = 60
    base[1]["suggested_duration_min"] = 60
    base[2]["suggested_duration_min"] = 120
    drum_near["suggested_duration_min"] = 90
    drum_away["suggested_duration_min"] = 90

    items_near = PlanningAgent._deterministic_selection(
        base + [drum_near], 2, {"西安": (1, 2)}
    )
    items_away = PlanningAgent._deterministic_selection(
        base + [drum_away], 2, {"西安": (1, 2)}
    )
    day_of = {it["name"]: it["day"] for it in items_near}
    assert day_of["鼓楼"] == day_of["钟楼"]  # 族内件跟锚同日
    day_of_b = {it["name"]: it["day"] for it in items_away}
    assert day_of_b["鼓楼"] != day_of_b["钟楼"]  # 族外件落别日（对照组）


# --- ④ 心愿覆盖认子站 --------------------------------------------------------


class RecordingItems:
    def __init__(self) -> None:
        self.updates: list = []

    def list_groups(self):
        return {"wishlist": [{"name": "西安鼓楼", "city": "西安", "id": "w1"}]}

    def update(self, *a, **k):
        self.updates.append((a, k))


def test_wishlist_covered_by_family_stop():
    picked = [
        _picked("西安钟楼", _ZL, 60),
        _picked("西安鼓楼", (_ZL[0] + 0.005, _ZL[1]), 90),
    ]
    cands = [
        _cand("西安钟楼", _ZL, "p-zl", "Bell Tower"),
        _cand("西安鼓楼", (_ZL[0] + 0.005, _ZL[1]), "p-gl", "Drum Tower"),
    ]
    items = RecordingItems()
    agent = PlanningAgent(BoomLLM(), auto_restaurants=False, trip_items=items)
    assumptions: list = []
    plan = asyncio.run(agent._assemble_plan(["西安"], 1, picked, cands, assumptions))
    session = PlanSession(session_id="s1", device_id="d1", cities=["西安"])
    session.plan = plan
    note = asyncio.run(agent._ensure_wishlist_coverage(session))
    # 鼓楼在族卡子站上 = 已在册：不回炉（note 空、零写库）
    assert note == ""
    assert items.updates == []
