"""近距独立双卡 + 伞名对多卡连排（2026-11-07 终裁）：

① ≤1km 同街族并卡已废（用户拍板「大雁塔和长安十二时辰应分两个 SITE
   连在一起，而不是完全合成一个景点」）：近距不同实体各排各卡，照常占
   4/日计数与预算；同日连排由近距同日圈承担。
② 伞名同站对还原多卡、连排成组合（2026-11-07 终裁「还原成多卡，但连
   排成一个组合一起参与排列，适合于所有城市」）：折卡（子站 chips）、
   影子退役、visit 去重三条吸收通道全部退役——博物馆×伞形景区两卡
   并存、各自时长、跨日由捆绑闸拉回同日连排。
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


# --- ② 伞名对还原多卡、同日连排（2026-11-07 终裁） ---------------------------
#
# 旧拍板（折卡/影子退役/visit 去重）已全退役：碑林博物馆×城墙·碑林景区
# 两卡并存，绑定必去必去标留在自己卡上，互替/子站披露不再出现。


def test_umbrella_pair_stays_two_cards_sameday():
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
    _, plan, assumptions = _family_plan([wall, beilin], cands)
    sights = _day1_sights(plan)
    assert {v.name for v in sights} == {
        "城墙·碑林历史文化景区",
        "西安碑林博物馆",
    }
    by_name = {v.name: v for v in sights}
    assert by_name["城墙·碑林历史文化景区"].duration_minutes == 180
    assert by_name["西安碑林博物馆"].duration_minutes == 90
    assert by_name["西安碑林博物馆"].must is True
    for card in sights:
        assert card.stops is None
    assert not any("互替" in a or "子站" in a for a in assumptions)


# --- ③ 心愿覆盖认本体卡（多卡口径） -------------------------------------------


class RecordingItems:
    def __init__(self) -> None:
        self.updates: list = []

    def list_groups(
        self, itinerary_id: str | None = None, owner_device_id: str | None = None
    ) -> dict:
        return {"wishlist": [{"name": "西安碑林博物馆", "city": "西安", "id": "w1"}]}

    def update(self, *a, **k):
        self.updates.append((a, k))


def test_wishlist_covered_by_own_card():
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
    # 碑林博物馆自己就是一张卡 = 已在册：不回炉（note 空、零写库）
    assert note == ""
    assert items.updates == []


# --- ④ 街区型经子站识别（solver 单元，历史会话的 chips 仍走此路径） ------------


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


# --- ⑤ 伞名对全链多卡语义（2026-11-07 终裁） ----------------------------------
#
# 吸收通道（折卡 _fam_twin_absorb / 影子退役 _museum_shadow_pairs /
# visit 去重 _umbrella_visit_dup）已退役删除；组合识别（捆绑闸）保留
# 且适用于所有城市：武侯祠博物馆×武侯祠·锦里（citywalk/street）跨日
# 拉回同日连排，两卡并存。


def _wuhou_museum():
    return {
        "name": "成都武侯祠博物馆",
        "city": "成都",
        "category": "museum",
        "source_poi_id": "p-whm",
        "name_en": "Wuhou Shrine Museum",
        "location": _loc((104.049, 30.645)),
    }


def _jinli_block():
    return {
        "name": "武侯祠·锦里",
        "city": "成都",
        "category": "citywalk",
        "source": "street",
        "source_poi_id": "p-jinli",
        "name_en": "Jinli Street",
        "location": _loc((104.048, 30.6455)),
    }


def test_citywalk_pair_multi_card_channels():
    from app.services.agent.plan import (
        _cand_diversity_group,
        _umbrella_cand_dup,
        _umbrella_specs_bundle,
    )

    assert _cand_diversity_group(_jinli_block()) == "citywalk"
    # 候选层默认口径（回填守卫 _dup_blocks_item 沿用）：citywalk 豁免
    # ——街区卡不构成回填层的伞名同站拦截
    assert _umbrella_cand_dup(_wuhou_museum(), _jinli_block()) is False
    # 组合识别不豁免：判同族，跨日拉回同日连排
    assert _umbrella_specs_bundle(_wuhou_museum(), _jinli_block()) is True
    # VisitItem 层伞名通道已退役：两卡不再互斥去重
    vi_block = VisitItem(
        item_id="i1",
        name="武侯祠·锦里",
        city="成都",
        day=1,
        category="citywalk",
    )
    vi_museum = VisitItem(
        item_id="i2",
        name="成都武侯祠博物馆",
        city="成都",
        day=1,
        category="museum",
    )
    from app.services.agent.plan import _same_visit

    assert _same_visit(vi_museum, vi_block) is False


def test_composite_channel_exempts_one_side_museum_only():
    # composite 通道豁免单侧博物馆对：武侯祠·锦里（复合挂牌拆段
    # 武侯祠）不再借 composite 吞掉武侯祠博物馆——伞名族回多卡连排；
    # 城墙·碑林 × 西安城墙（2026-11-04 城墙双卡案，双 attraction）
    # 与 museum×museum 原语义不动。
    from app.services.agent.plan import _same_visit
    from app.services.itinerary.models import GeoPoint

    wuhou_pair = (
        VisitItem(
            item_id="i1",
            name="成都武侯祠博物馆",
            city="成都",
            day=1,
            category="museum",
            location=GeoPoint(lon=104.049, lat=30.645),
        ),
        VisitItem(
            item_id="i2",
            name="武侯祠·锦里",
            city="成都",
            day=1,
            category="attraction",
            location=GeoPoint(lon=104.048, lat=30.6455),
        ),
    )
    assert _same_visit(*wuhou_pair) is False

    wall_pair = (
        VisitItem(
            item_id="i3",
            name="城墙·碑林历史文化景区",
            city="西安",
            day=1,
            category="attraction",
            location=GeoPoint(lon=108.9405, lat=34.2569),
        ),
        VisitItem(
            item_id="i4",
            name="西安城墙",
            city="西安",
            day=1,
            category="attraction",
            location=GeoPoint(lon=108.929, lat=34.2759),
        ),
    )
    assert _same_visit(*wall_pair) is True

    museum_pair = (
        VisitItem(
            item_id="i5",
            name="陕西历史博物馆",
            city="西安",
            day=1,
            category="museum",
        ),
        VisitItem(
            item_id="i6",
            name="陕西历史博物馆·秦汉馆",
            city="西安",
            day=1,
            category="museum",
        ),
    )
    assert _same_visit(*museum_pair) is True


def test_beilin_umbrella_semantics_unchanged():
    # 对照：attraction 伞形挂牌行（非 citywalk 类）伞名同站照常识别
    # ——回填守卫与组合识别闸共用此判定
    wall = {
        "name": "城墙·碑林历史文化景区",
        "city": "西安",
        "category": "attraction",
        "source_poi_id": "p-wall",
        "location": _loc(_ZL),
    }
    beilin = {
        "name": "西安碑林博物馆",
        "city": "西安",
        "category": "museum",
        "source_poi_id": "p-bl",
        "location": _loc(_ZL),
    }
    from app.services.agent.plan import _umbrella_cand_dup

    assert _umbrella_cand_dup(beilin, wall) is True


def test_bucket_counts_street_source_as_citywalk():
    from app.services.agent.plan import _itin_cap_bucket

    # street 源行（cat 非 citywalk）与 cat=citywalk 同入 citywalk 桶
    assert _itin_cap_bucket(_jinli_block()) == "citywalk"
    street_attraction = {
        "name": "春熙路",
        "city": "成都",
        "category": "attraction",
        "source": "street",
    }
    assert _itin_cap_bucket(street_attraction) == "citywalk"


def test_bundle_recognizes_citywalk_pair_for_sameday():
    # 组合识别全城适用（2026-11-07 终裁）：跨日的武侯祠博物馆×武侯祠·
    # 锦里判同族、拉回同日连排。rank 实测：street 源 tier=8 < museum3
    # 无档 tier=11 → 锦里档高是 keeper，博物馆被拉到锦里的日。
    from app.services.agent.plan import (
        _bundle_umbrella_spec_days,
        _umbrella_specs_bundle,
    )

    assert _umbrella_specs_bundle(_wuhou_museum(), _jinli_block()) is True

    museum = {**_wuhou_museum(), "day": 2, "duration_minutes": 90}
    jinli = {**_jinli_block(), "day": 4, "duration_minutes": 120}
    notes = _bundle_umbrella_spec_days(
        [museum, jinli],
        {
            "成都武侯祠博物馆": _wuhou_museum(),
            "武侯祠·锦里": _jinli_block(),
        },
    )
    assert notes == ["成都武侯祠博物馆→武侯祠·锦里"]
    assert museum["day"] == 4 and jinli["day"] == 4
