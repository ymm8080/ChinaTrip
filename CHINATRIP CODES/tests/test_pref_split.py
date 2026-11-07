"""偏好/心愿分层（2026-10-31 用户拍板，三条合成口径）。

①心愿=一次性满足的具体要求（看熊猫→基地，排一次翻已排期）→ 建心愿行；
②偏好=品类倾向，行程里可以出现同一类型的多个景点 → 只作选点排序信号，
不建心愿行；③选点当然要优先用户偏好的品类（偏好同类提到 tier 之前，
同偏好组内仍按 tier 保库序）。线上回归：LLM 曾把「偏好：无特别要求」
原话列进 wishes，心愿单出现同名行——偏好性元话语建行前丢弃。
"""

from __future__ import annotations

import asyncio
import json

from app.services.agent.plan import (
    PlanningAgent,
    _is_preference_meta,
    _is_preference_style_option,
    _preference_tokens,
)
from app.services.llm.base import ChatResult
from app.services.llm.zhipu import LLMError
from app.services.poi_details import PoiDetailStore
from app.services.trip_items import TripItemService

# 本文件不设 PLAN_SELECT_MODE：默认算法模式选点（偏好排序的主路径），
# 且偏好问答整链零 LLM 调用由 BoomLLM 哨兵守护。


class CountingBoomLLM:
    """任何调用都是事故哨兵——同时计数以便断言「零烧 LLM」。"""

    name = "boom"

    def __init__(self):
        self.calls = 0

    async def chat(self, messages, *, temperature=0.3, max_tokens=None, **kwargs):
        self.calls += 1
        raise LLMError("preference round must not burn the LLM")


class ScriptedLLM:
    """按序吐 canned 回复；计数 chat() 调用。"""

    name = "scripted"

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls = 0

    async def chat(
        self, messages, *, temperature: float = 0.3, max_tokens=None
    ) -> ChatResult:
        self.calls += 1
        assert self.replies, "scripted replies exhausted"
        return ChatResult(content=self.replies.pop(0), model="scripted")


class DistanceAmap:
    """amap 桩：检索吐固定 POIS；腿/时长恒定（enrich 路径够用）。"""

    def __init__(self, pois=None, meters=1100, seconds=900):
        self.pois = pois or []
        self.meters = meters
        self.seconds = seconds
        self.calls: list = []

    async def search_poi(self, keywords, *, city=None, page=1):
        self.calls.append((keywords, city))
        return self.pois

    async def walking_route(
        self, origin, destination, *, origin_id=None, destination_id=None
    ):
        return {
            "distance_m": self.meters,
            "duration_s": self.seconds,
            "steps": [],
            "polyline": [],
        }

    async def place_hours(self, poi_id):
        return {"opening_hours": "09:00-17:00", "rating": "4.8"}

    async def search_hours(self, keyword, city=None):
        return {
            "opening_hours": "09:00-21:00",
            "rating": None,
            "matched": keyword,
            "poi_id": "B00TEST01",
        }


_CD_POIS = [
    {
        "name": "成都博物馆",
        "city": "成都",
        "category": "博物馆",
        "source_poi_id": "B-CD-MUSEUM",
        "location": {"lon": 104.06, "lat": 30.66},
        "address": "天府广场",
        "opening_hours": "09:00-17:00",
    },
    {
        "name": "宽窄巷子",
        "city": "成都",
        "category": "风景名胜",
        "source_poi_id": "B-CD-KZZ",
        "location": {"lon": 104.05, "lat": 30.66},
        "address": "长顺街",
        "opening_hours": "全天",
    },
]


def run(coro):
    return asyncio.run(coro)


def edit_reply(reply: str, diffs, need=None, wishes=None) -> str:
    payload = {"reply": reply, "diffs": diffs, "need_clarification": need or []}
    if wishes is not None:
        payload["wishes"] = wishes
    return json.dumps(payload, ensure_ascii=False)


def _all_rows(svc: TripItemService) -> list[dict]:
    return [i for group in svc.list_groups(None).values() for i in group]


def _cand(
    name,
    city="成都",
    *,
    cat="sight",
    tags=None,
    loc=None,
    rain_ok=None,
    dur=None,
):
    c: dict = {"name": name, "city": city, "category": cat}
    if tags is not None:
        c["tags"] = tags
    if loc is not None:
        c["location"] = loc
    if rain_ok is not None:
        c["rain_ok"] = rain_ok
    if dur is not None:
        c["suggested_duration_min"] = dur
    return c


# --- 偏好问答回复：品类/风格词只当偏好，不建心愿行 -------------------------


def test_pref_round_category_reply_stays_preference_no_row():
    """拍板②：回「博物馆人文」是品类倾向——不建心愿行、不烧语义绑定；
    偏好由选点排序兑现（成都博物馆同类优先），假设区留痕。"""
    llm = CountingBoomLLM()
    svc = TripItemService()
    agent = PlanningAgent(
        llm,
        amap_client=DistanceAmap([dict(p) for p in _CD_POIS]),
        poi_details=PoiDetailStore(),
        trip_items=svc,
        auto_restaurants=False,
    )
    session = run(agent.start(device_id="d1", cities=["成都"], days=2))
    assert session.state == "clarify" and session.pref_asked is True
    session, _reply, _ = run(agent.message(session, "博物馆人文"))
    assert session.state == "ready"
    assert session.preferences == "博物馆人文"
    assert session.plan is not None and session.plan.days
    rows = _all_rows(svc)
    assert not any("博物馆人文" in (i.get("name") or "") for i in rows)
    # 品类兑现留痕：候选里有同类（成都博物馆）→ 假设区可见偏好已生效
    assert any("已按偏好优先安排同类景点" in a for a in session.assumptions)
    # 整链零 LLM（算法选点 + 品类词不再走语义绑定）
    assert llm.calls == 0


def test_pref_round_style_option_reply_stays_preference_no_row():
    """拍板②：题面风格选项（自然风光）同样只是偏好——不建行；且在
    品类词表之外的风格词也不烧绑定调用（旧版会试绑一次）。"""
    llm = CountingBoomLLM()
    svc = TripItemService()
    agent = PlanningAgent(
        llm,
        amap_client=DistanceAmap([dict(p) for p in _CD_POIS]),
        poi_details=PoiDetailStore(),
        trip_items=svc,
        auto_restaurants=False,
    )
    session = run(agent.start(device_id="d1", cities=["成都"], days=2))
    session, _reply, _ = run(agent.message(session, "自然风光"))
    assert session.state == "ready"
    assert session.preferences == "自然风光"
    rows = _all_rows(svc)
    assert not any("自然风光" in (i.get("name") or "") for i in rows)
    assert llm.calls == 0


def test_pref_round_specific_wish_still_builds_row():
    """拍板①同时成立：点名具体对象的回复（看熊猫）仍走心愿管线建行——
    语义绑定命中真实 POI 即可，不依赖 LLM（库内核心词路径）。"""
    store = PoiDetailStore()
    store.upsert(
        "B-PANDA-BASE",
        city="成都",
        name="成都大熊猫繁育研究基地",
        location=(104.1441, 30.7327),
    )
    llm = CountingBoomLLM()
    svc = TripItemService()
    agent = PlanningAgent(
        llm,
        amap_client=DistanceAmap([dict(p) for p in _CD_POIS]),
        poi_details=store,
        trip_items=svc,
        auto_restaurants=False,
    )
    session = run(agent.start(device_id="d1", cities=["成都"], days=2))
    session, _reply, _ = run(agent.message(session, "看熊猫"))
    assert session.state == "ready"
    assert session.preferences == "看熊猫"
    rows = _all_rows(svc)
    assert any((i.get("name") or "") == "看熊猫" for i in rows), "具体愿望仍须逐字建行"
    names = [
        getattr(v, "name", "")
        for d in session.plan.days
        for v in d.items
        if getattr(v, "category", "") != "food"
    ]
    assert "成都大熊猫繁育研究基地" in names


# --- 主聊天道：偏好性元话语不是愿望 ---------------------------------------


def test_chat_meta_preference_phrase_creates_no_wishlist_row():
    """线上回归（2026-10-31 12:44 上海会话 it-02287fad）：LLM 把
    「偏好：无特别要求」原话列进 wishes 建了心愿行——建行前丢弃。"""
    llm = ScriptedLLM([edit_reply("好的", [], wishes=["偏好：无特别要求"])])
    svc = TripItemService()
    agent = PlanningAgent(
        llm,
        amap_client=DistanceAmap([dict(p) for p in _CD_POIS]),
        poi_details=PoiDetailStore(),
        trip_items=svc,
        auto_restaurants=False,
    )
    session = run(
        agent.start(device_id="d1", cities=["成都"], days=2, preferences="亲子")
    )
    assert session.state == "ready"
    session, _reply, _ = run(agent.message(session, "无特别要求"))
    rows = _all_rows(svc)
    assert not any("无特别要求" in (i.get("name") or "") for i in rows)
    assert llm.calls == 1  # 只烧编辑回合那一次


def test_chat_style_option_phrase_creates_no_wishlist_row():
    """风格选项词（慢慢逛）从聊天道列进 wishes 同样不建行——它落不了
    任何具体地点，建行只会变成无坐标占位卡。"""
    llm = ScriptedLLM([edit_reply("好的", [], wishes=["慢慢逛"])])
    svc = TripItemService()
    agent = PlanningAgent(
        llm,
        amap_client=DistanceAmap([dict(p) for p in _CD_POIS]),
        poi_details=PoiDetailStore(),
        trip_items=svc,
        auto_restaurants=False,
    )
    session = run(
        agent.start(device_id="d1", cities=["成都"], days=2, preferences="亲子")
    )
    session, _reply, _ = run(agent.message(session, "慢慢逛"))
    rows = _all_rows(svc)
    assert not any((i.get("name") or "") == "慢慢逛" for i in rows)


# --- 吸收层：历史误建的偏好行不再变必去 -----------------------------------


def test_absorb_skips_preference_meta_and_style_rows():
    svc = TripItemService()
    svc.create("看熊猫", source="chat", city="成都")
    svc.create("偏好：无特别要求", source="chat", city=None)
    svc.create("慢慢逛", source="chat", city=None)
    llm = CountingBoomLLM()
    agent = PlanningAgent(
        llm,
        amap_client=DistanceAmap([dict(p) for p in _CD_POIS]),
        poi_details=PoiDetailStore(),
        trip_items=svc,
        auto_restaurants=False,
    )
    session = run(
        agent.start(device_id="d1", cities=["成都"], days=2, preferences="亲子")
    )
    assert session.state == "ready"
    assert "看熊猫" in session.must_visits
    assert "慢慢逛" not in session.must_visits
    assert not any("无特别要求" in m for m in session.must_visits)


# --- 选点：偏好同类优先（拍板③，同类可多个） ------------------------------


def test_selection_prefers_user_category_ahead_of_tier():
    cands = [
        _cand("五A景区甲", tags=["5a"]),
        _cand("社区博物馆乙", cat="museum"),
        _cand("五A景区乙", tags=["5a"]),
        _cand("城市美术馆", cat="museum"),
    ]
    items = PlanningAgent._deterministic_selection(
        cands, 1, {"成都": (1, 1)}, preferences="博物馆人文"
    )
    names = [it["name"] for it in items]
    # 偏好同类（museum，tier 9）提到 5A（tier 2）之前；同组内库序；
    # 偏好命中同时豁免行程桶上限（两家博物馆都保留，2026-11-07 口径）
    assert names == ["社区博物馆乙", "城市美术馆", "五A景区甲", "五A景区乙"]
    # 无偏好时恢复 tier 序 + 行程桶上限（博物馆类每行程 1 家，11-07 拍板）
    base = PlanningAgent._deterministic_selection(
        [dict(c) for c in cands], 1, {"成都": (1, 1)}
    )
    assert [it["name"] for it in base] == [
        "五A景区甲",
        "五A景区乙",
        "社区博物馆乙",
    ]


def test_selection_nature_free_text_preference():
    cands = [
        _cand("城市地标塔", tags=["5a"]),
        _cand("青溪湖湿地公园", cat="nature"),
        _cand("峡谷观景台", cat="viewpoint"),
    ]
    items = PlanningAgent._deterministic_selection(
        cands, 1, {"成都": (1, 1)}, preferences="喜欢自然风光"
    )
    assert [it["name"] for it in items] == [
        "青溪湖湿地公园",
        "峡谷观景台",
        "城市地标塔",
    ]


def test_selection_pref_rank_survives_rain_reorder():
    """雨天重排：避险位（室内优先）仍在偏好位之前，偏好位在 tier 之前。"""
    cands = [
        _cand("室内五A馆", tags=["5a"], rain_ok="yes"),
        _cand("社区博物馆", rain_ok="yes", cat="museum"),
        _cand("露天自然点", rain_ok="no", cat="nature"),
    ]
    items = PlanningAgent._deterministic_selection(
        cands,
        1,
        {"成都": (1, 1)},
        rain_days={"成都": {1}},
        preferences="博物馆人文",
    )
    names = [it["name"] for it in items]
    # 雨日硬闸（2026-11-02）：单日窗无干日 → 露天出局；室内序=
    # 避险位>偏好位（社区博物馆偏好命中排在 5A 之前）
    assert names == ["社区博物馆", "室内五A馆"]


# --- 偏好识别与映射 helper -------------------------------------------------


def test_preference_meta_and_style_detection():
    assert _is_preference_meta("偏好：无特别要求")
    assert _is_preference_meta("No preference")
    assert _is_preference_meta("都可以")
    assert not _is_preference_meta("看熊猫")
    assert not _is_preference_meta("想去都江堰看水利工程")
    assert _is_preference_style_option("自然风光")
    assert _is_preference_style_option("慢慢逛")
    assert not _is_preference_style_option("看熊猫")


def test_preference_tokens_union_and_show():
    toks, show = _preference_tokens("喜欢博物馆和美食")
    assert "博物馆" in toks and "夜市" in toks
    assert not show
    toks2, show2 = _preference_tokens("看演出")
    assert show2 and "演出" in toks2
    empty, no_show = _preference_tokens("")
    assert empty == () and not no_show
