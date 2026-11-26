# -*- coding: utf-8 -*-
"""行前卡闸与 LLM 读句（2026-11-17 用户拍板）。

/plan/start 文字输入：正则读不出日期/天数时先问 LLM（LLM UNDERSTAND
DATE, TIME DURATION ETC）；LLM 也读不出才弹行前卡。只写一个日期 = 一日
游，不再弹卡；没有任何日期仍弹（2026-11-15 口径保持）。复用 test_plan_api
的装配。
"""

import json

from test_plan_api import DEVICE_HEADERS, V0_JSON, StubAdapter, client_for, start

from app.services.agent.plan import PlanningAgent


class _GateLLM:
    name = "gate-scripted"

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls = 0

    async def chat(self, messages, *, temperature: float = 0.3, max_tokens=None):
        from app.services.llm.base import ChatResult

        self.calls += 1
        assert self.replies, "scripted replies exhausted"
        return ChatResult(content=self.replies.pop(0), model="gate-scripted")


class _GateStore:
    """读句用底库桩：ZHUJIAZUI 只能靠 LLM 通道纠错，ZHUJIAJIAO 直接命中。"""

    def match_text_names(self, city, text, *, limit=8):
        low = (text or "").lower()
        if "zhujiajiao" in low or "朱家角" in (text or ""):
            return [
                {
                    "name": "朱家角古镇",
                    "name_en": "Zhujiajiao Ancient Town",
                    "city": "上海",
                    "category": "sight",
                }
            ]
        return []

    def candidate_by_name(self, city, name):
        if name == "朱家角古镇":
            return {"name": "朱家角古镇", "city": "上海", "category": "sight"}
        return None

    def name_city_spread(self, name):
        return ["上海"] if name == "朱家角古镇" else []

    # 表单开局要真跑到生成：给空底库实现，避免桩缺方法 500（非本闸断言对象）。
    def db_degraded(self):
        return False

    def top_pois_in_city(self, city, limit=30, *, exclude_food=True):
        return []

    def search_keyword(self, city, tokens, *, limit=5):
        return []

    def get_by_name(self, city, name):
        return None

    def get(self, source_poi_id):
        return None

    def upsert(self, *a, **k):
        return None


def _sites(name="朱家角古镇"):
    return json.dumps(
        {"sites": [{"name": name, "kind": "sight", "city": "上海", "day": 0}]},
        ensure_ascii=False,
    )


def _facts(**kw):
    payload = {"city": None, "start_date": None, "days": None, "day1_start": None}
    payload.update(kw)
    return json.dumps(payload, ensure_ascii=False)


def test_no_intake_for_single_english_date_comment():
    # 真实案（会话 fc573cde）：正则已读出 Dec.02+一日 → 闸直接放行；
    # agent.start 里 LLM facts 读句补城市，读点轮照开。
    llm = _GateLLM(
        [
            _facts(city="上海", start_date="2026-12-02", days=1, day1_start="11:00"),
            _sites(),
        ]
    )
    agent = PlanningAgent(llm, amap_client=None, poi_details=_GateStore())
    resp = start(
        client_for(agent),
        {
            "preferences": (
                "I WANT TO GO TO ZHUJIAZUI ON DEC.02. LEAVE HOTEL ON 11AM, PLS ARRANGE"
            )
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "site_confirm"
    assert body["sites"] == ["朱家角古镇"]


def test_gate_asks_llm_when_regex_cannot_read_date():
    # 正则读不出的日期（Christmas time）→ 闸先问 LLM；LLM 给出日期+天数
    # → 不弹行前卡（城市没给 → clarify 问城市，但那不是行前卡）。
    llm = _GateLLM(
        [
            _facts(start_date="2026-12-25", days=2),
            _facts(),  # start() 里 facts 城市空 → 再问一次（返回空）
            json.dumps({"sites": []}, ensure_ascii=False),  # 点名反推无果
        ]
    )
    agent = PlanningAgent(llm, amap_client=None, poi_details=_GateStore())
    resp = start(
        client_for(agent),
        {"preferences": "trip sometime around Christmas time, two days"},
    )
    body = resp.json()
    assert body["state"] == "clarify"
    assert llm.calls >= 1


def test_intake_still_shown_when_llm_also_blank():
    agent = PlanningAgent(None, amap_client=None, poi_details=_GateStore())
    resp = start(client_for(agent), {"preferences": "museums and local food please"})
    body = resp.json()
    assert body["state"] == "intake"
    assert body.get("start_date_hint") is None


def test_intake_not_shown_for_date_range_days_derived():
    # 起止两个日期=完整信息（2026-11-23 用户拍板「IF I INPUT ENOUGH
    # INFORMATION, THERE SHOULD BE NO POP UP WINDOW」）：天数=首末跨度正则
    # 直推（Nov 20 to Nov 22=3），不弹行前卡；缺的是城市 → 走追问城市，
    # 不弹卡。旧口径「区间没写天数仍要问」被本拍板取代（11-23 早实锤：
    # LLM 周配额 429 全灭，区间句被弹卡、用户被迫手填卡里已有的日期）。
    agent = PlanningAgent(None, amap_client=None, poi_details=_GateStore())
    resp = start(client_for(agent), {"preferences": "trip from Nov 20 to Nov 22"})
    body = resp.json()
    assert body["state"] != "intake"


def test_intake_not_shown_for_form_with_preferences_date_range():
    # 表单已填城市/天数 + 偏好文本写起止日期（H5 常规开局把自由输入折进
    # preferences）：日期仍在用户给的信息里，不能因为表单有值就把日期
    # 文本置空、再弹行前卡（2026-11-23 实报 form+pref range ⇒ intake）。
    agent = PlanningAgent(
        StubAdapter([V0_JSON]), amap_client=None, poi_details=_GateStore()
    )
    resp = start(
        client_for(agent),
        {
            "cities": ["北京"],
            "days": 8,
            "preferences": "Nov 30 to Dec 7 Beijing",
        },
    )
    body = resp.json()
    assert body["state"] != "intake"
    assert body.get("start_date_hint") is None


def test_intake_not_shown_for_form_cities_with_preferences_date_range():
    # 表单只给城市、没给天数/日期，偏好文本给起止日期：跨度既是天数也是
    # 出发日依据，仍属信息给足——不弹行前卡。
    agent = PlanningAgent(
        StubAdapter([V0_JSON]), amap_client=None, poi_details=_GateStore()
    )
    resp = start(
        client_for(agent),
        {"cities": ["北京"], "preferences": "Nov 30 to Dec 7"},
    )
    body = resp.json()
    assert body["state"] != "intake"
    assert body.get("start_date_hint") is None


def test_intake_not_shown_when_date_only_in_preferences_with_brief_city():
    # 主输入只写城市、日期写在偏好栏（H5 分栏输入；brief=北京，
    # preferences=Nov 30 to Dec 7）：日期仍在用户给的信息里，不能只看
    # brief 就判信息不足再弹卡。
    agent = PlanningAgent(
        StubAdapter([V0_JSON]), amap_client=None, poi_details=_GateStore()
    )
    # 直发 client：test_plan_api.start() 会给表单用例补 start_date，掩盖
    # 「日期只在 preferences」这条缝。
    resp = client_for(agent).post(
        "/api/v1/plan/start",
        json={
            "cities": ["北京"],
            "brief": "北京",
            "preferences": "Nov 30 to Dec 7",
        },
        headers=DEVICE_HEADERS,
    )
    body = resp.json()
    assert body["state"] != "intake"
    assert body.get("start_date_hint") is None
    assert (body.get("plan") or {}).get("start_date") == "2026-11-30"


def test_intake_not_shown_when_form_days_present():
    # 表单天数在：不看 preferences 文本弹卡（表单用户不打扰）
    agent = PlanningAgent(None, amap_client=None, poi_details=_GateStore())
    resp = start(
        client_for(agent),
        {"days": 2, "preferences": "I want to go on DEC.02."},
    )
    body = resp.json()
    assert body["state"] != "intake"
