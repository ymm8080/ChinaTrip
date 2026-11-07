"""近距独立双卡 + 同站折卡（2026-11-07 反转拍板）：

① ≤1km 同街族并卡已废（用户拍板「大雁塔和长安十二时辰应分两个 SITE
   连在一起，而不是完全合成一个景点」）：近距不同实体各排各卡，照常占
   4/日计数与预算；同日连排由 1.5km 贴邻圈承担。
② 同站伞名折卡保留（碑林双卡案三拍「先类型二选一，再聚合；要显示出
   来，不许影没」）：伞名同站的博物馆本体折进伞形景区主卡当子站 chip，
   时长取最长一站、必去标随主卡、心愿落子站=已在册不回炉。
"""

from __future__ import annotations

import asyncio

from app.services.agent.plan import PlanningAgent, PlanSession
from app.services.itinerary import VisitItem
from app.services.itinerary.models import PlanStop
from app.services.itinerary.solver import _is_citywalk, _is_theme_block
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


def _picked(name, loc, minutes, *, must=False, category="sight"):
    return {
        "name": name,
        "city": "西安",
        "day": 1,
        "duration_minutes": minutes,
        "category": category,
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


# --- ① 反转回归：≤1km 不同实体保持两张独立卡（2026-11-07 反转拍板） --------


def _family_plan(picked, cands):
    agent = PlanningAgent(BoomLLM(), auto_restaurants=False)
    assumptions: list = []
    plan = asyncio.run(
        agent._assemble_plan(
            ["西安"], 1, picked, cands, assumptions, start_date="2026-11-16"
        )
    )
    return agent, plan, assumptions


def _day1_sights(plan):
    return [
        v
        for v in plan.days[0].items
        if isinstance(v, VisitItem) and v.category not in ("food", "hotel")
    ]


def test_nearby_distinct_stays_two_cards():
    # 大雁塔(180) + 0.74km 外的长安十二时辰街区(240)：两个真实景点，
    # 不合成一卡——各排各卡、各自时长、无子站 chips、无同街并卡披露。
    dyt = (_ZL[0] + 0.008, _ZL[1])  # ~0.74km
    picked = [
        _picked("大雁塔大唐芙蓉园景区", _ZL, 180),
        {
            **_picked("长安十二时辰主题街区", dyt, 240),
            "category": "entertainment",
        },
    ]
    cands = [
        _cand("大雁塔大唐芙蓉园景区", _ZL, "p-dyt", "Dayanta"),
        _cand("长安十二时辰主题街区", dyt, "p-sec", "Twelve Hours Block"),
    ]
    _, plan, assumptions = _family_plan(picked, cands)
    sights = _day1_sights(plan)
    assert {v.name for v in sights} == {
        "大雁塔大唐芙蓉园景区",
        "长安十二时辰主题街区",
    }
    for card in sights:
        assert card.stops is None
    by_name = {v.name: v for v in sights}
    assert by_name["大雁塔大唐芙蓉园景区"].duration_minutes == 180
    assert by_name["长安十二时辰主题街区"].duration_minutes == 240
    assert not any("同街" in a for a in assumptions)


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
    sights = _day1_sights(plan)
    assert len(sights) == 2
    card = next(v for v in sights if v.name == "西安钟楼")
    assert card.stops is None


# --- ② 同站伞名折卡保留（碑林双卡案三拍） ------------------------------------


def test_twin_absorb_still_folds_at_assembly():
    # 绑定行「西安碑林博物馆」无坐标（_enrich_parallel 之后才补），
    # 与伞形挂牌行「城墙·碑林历史文化景区」伞名同站（同城+词素降级闸）
    # → 折进主卡当子站 chip：单卡、时长取最长、必去标随主卡、披露互替。
    wall = _picked("城墙·碑林历史文化景区", _ZL, 180)
    beilin = {
        "name": "西安碑林博物馆",
        "city": "西安",
        "day": 1,
        "duration_minutes": 90,
        "category": "museum",
        "must": True,
        "source_poi_id": "p-bl",
    }
    cands = [
        _cand("城墙·碑林历史文化景区", _ZL, "p-wall", "City Wall Scenic Area"),
        {
            "name": "西安碑林博物馆",
            "city": "西安",
            "category": "museum",
            "source_poi_id": "p-bl",
            "name_en": "Stele Forest Museum",
        },
    ]
    agent, plan, assumptions = _family_plan([wall, beilin], cands)
    sights = _day1_sights(plan)
    assert {v.name for v in sights} == {"城墙·碑林历史文化景区"}
    card = sights[0]
    assert [s.name for s in card.stops] == ["西安碑林博物馆"]
    assert card.stops[0].poi_id == "p-bl"
    assert card.duration_minutes == 180
    assert card.must is True
    assert any("子站" in a for a in assumptions)
    # 必去子站保护映射：子站名扩到主卡名（铁律 19 protect 口径）
    assert agent._family_must_names({"西安碑林博物馆"}) == {
        "西安碑林博物馆",
        "城墙·碑林历史文化景区",
    }


# --- ③ 心愿覆盖认子站（伞名折卡口径） ----------------------------------------


class RecordingItems:
    def __init__(self) -> None:
        self.updates: list = []

    def list_groups(self):
        return {"wishlist": [{"name": "西安碑林博物馆", "city": "西安", "id": "w1"}]}

    def update(self, *a, **k):
        self.updates.append((a, k))


def test_wishlist_covered_by_twin_stop():
    wall = _picked("城墙·碑林历史文化景区", _ZL, 180)
    beilin = {
        "name": "西安碑林博物馆",
        "city": "西安",
        "day": 1,
        "duration_minutes": 90,
        "category": "museum",
        "source_poi_id": "p-bl",
    }
    cands = [
        _cand("城墙·碑林历史文化景区", _ZL, "p-wall", "City Wall Scenic Area"),
        {
            "name": "西安碑林博物馆",
            "city": "西安",
            "category": "museum",
            "source_poi_id": "p-bl",
            "name_en": "Stele Forest Museum",
        },
    ]
    items = RecordingItems()
    agent = PlanningAgent(BoomLLM(), auto_restaurants=False, trip_items=items)
    assumptions: list = []
    plan = asyncio.run(
        agent._assemble_plan(["西安"], 1, [wall, beilin], cands, assumptions)
    )
    session = PlanSession(session_id="s1", device_id="d1", cities=["西安"])
    session.plan = plan
    note = asyncio.run(agent._ensure_wishlist_coverage(session))
    # 碑林博物馆在主卡子站 chip 上 = 已在册：不回炉（note 空、零写库）
    assert note == ""
    assert items.updates == []


# --- ④ 街区型经子站识别（solver 单元，折卡 chips 仍走此路径） -----------------


def test_theme_block_recognized_via_stops():
    # 主卡名是锚名（无「街区」二字）——_is_theme_block 必须扫到
    # 子站名/类别才认得出夜档街区形态；普通锚（无街区子站）保持 False，
    # 也不会被误判成 13:00 口径的普通 citywalk。
    fam = VisitItem(
        item_id="i1",
        name="大雁塔大唐芙蓉园景区",
        city="西安",
        day=1,
        category="attraction",
        duration_minutes=240,
        stops=[
            PlanStop(
                name="长安十二时辰主题街区",
                category="entertainment",
                duration_minutes=240,
            )
        ],
    )
    plain = VisitItem(
        item_id="i2",
        name="大雁塔大唐芙蓉园景区",
        city="西安",
        day=1,
        category="attraction",
        duration_minutes=240,
    )
    assert _is_theme_block(fam) is True
    assert _is_theme_block(plain) is False
    assert _is_citywalk(fam) is False
