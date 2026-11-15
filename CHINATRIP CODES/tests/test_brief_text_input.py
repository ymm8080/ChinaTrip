"""自由输入读点（2026-11-14 用户实报「规划引擎根本不读输入」）。

起步页那段英文行程描述此前整段被丢：天数读不出（"Over two days"）、
城市被表单默认值压掉（表单永远至少有出发城，"城市为空才读偏好"的兜底
是死路）、点名的景点从来没进过必去（偏好只按品类 token 消费，英文描述
一个都不中）。这里覆盖三层修复。
"""

import asyncio
import json

from app.services.agent.plan import (
    PlanningAgent,
    PlanSession,
    _parse_days,
    _trip_brief,
)
from app.services.llm.base import ChatResult
from app.services.poi_details import PoiDetailStore

TEXT = (
    "Spend less time planning and more time exploring Beijing on this comprehensive "
    "small-group tour. Over two days, see the highlights of the city, starting with a "
    "tour of Tiananmen Square and the Forbidden City. Then, it's on to see the Great "
    "Wall of China at Mutianyu, walking along the ramparts of the UNESCO World "
    "Heritage-listed structure. On day two, visit the Temple of Heaven, enjoy a "
    "rickshaw ride through the old Hutong district, and conclude the tour at the "
    "Summer Palace."
)


class ScriptedLLM:
    """Canned replies in order; records the prompts it saw."""

    name = "scripted"

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls = 0
        self.system_prompts: list[str] = []

    async def chat(self, messages, *, temperature: float = 0.3, max_tokens=None):
        self.calls += 1
        self.system_prompts.append(messages[0].content)
        assert self.replies, "scripted replies exhausted"
        return ChatResult(content=self.replies.pop(0), model="scripted")


class ExplodingLLM:
    """Any call is a bug sentinel."""

    name = "explode"

    async def chat(self, messages, *, temperature: float = 0.3, max_tokens=None):
        raise AssertionError("LLM must not be called here")


class SitesStore(PoiDetailStore):
    """底库桩：match_text_names 按城市返回命中的行，candidate_by_name 查表。"""

    def __init__(self, rows_by_city=None, known=None) -> None:
        super().__init__()
        self.rows_by_city = rows_by_city or {}
        self.known = known or {}
        self.match_calls: list[tuple[str, str]] = []
        self.lookup_calls: list[tuple[str, str]] = []

    def match_text_names(self, city, text, *, limit=8):
        self.match_calls.append((city, text))
        return list(self.rows_by_city.get(city, []))

    def candidate_by_name(self, city, name):
        self.lookup_calls.append((city, name))
        return self.known.get((city, name))


def run(coro):
    return asyncio.run(coro)


def _sites_reply(*items) -> str:
    """Name-only entries or (name, day) pairs."""
    sites = []
    for item in items:
        name, day = (item, 0) if isinstance(item, str) else item
        sites.append({"name": name, "kind": "sight", "city": "北京", "day": day})
    return json.dumps({"sites": sites}, ensure_ascii=False)


def _session(**kwargs) -> PlanSession:
    data = {
        "session_id": "s-brief",
        "device_id": "d1",
        "cities": ["北京"],
        "days": 2,
        "preferences": TEXT,
        "brief_text": TEXT,
    }
    data.update(kwargs)
    return PlanSession(**data)


# --- ① 天数 ---------------------------------------------------------------


def test_parse_days_reads_english_counts():
    assert _parse_days("Over two days, see the highlights") == 2
    assert _parse_days("a 2-day tour of Beijing") == 2
    assert _parse_days("two-day tour") == 2
    assert _parse_days("5 days in Beijing") == 5
    assert _parse_days("twenty-one days") == 21
    # 中文口径不受影响
    assert _parse_days("三日游") == 3
    assert _parse_days("就 5 个人玩") == 5


def test_parse_days_ignores_day_ordinals():
    # 「On day two」是行程内序数，不是趟数——否则 5 天行程读到 day 2 就被改短
    assert _parse_days("On day two, visit the Temple of Heaven") is None
    assert _parse_days("day two is the Great Wall") is None
    # 数字序数（day 3）落在旧「裸数字=天数」兜底上，行为不变
    assert _parse_days("3-day tour") == 3


def test_trip_brief_reads_english_trip():
    assert _trip_brief(TEXT) == (["北京"], 2)
    # 单城、无天数：仍是「改当前行程」语义，不算整趟简报
    assert _trip_brief("北京") is None


# --- ② 起步页文本压过表单默认值 ------------------------------------------


class _StopAfterStart(PlanningAgent):
    """停在 start()：本测试只验路线解析，不进生成管线。"""

    async def _generate_v0(self, session, *, extra_assumptions=None):
        return session


def test_start_lets_typed_brief_beat_form_defaults():
    agent = _StopAfterStart(
        ExplodingLLM(), amap_client=None, poi_details=SitesStore()
    )
    session = run(
        agent.start(
            device_id="d1",
            cities=["上海"],
            days=2,
            preferences=TEXT,
            brief=TEXT,
            lang="en",
        )
    )
    assert session.cities == ["北京"]
    assert session.days == 2
    assert session.city_days == {}
    assert session.brief_text == TEXT


def test_start_brief_without_day_count_keeps_form_days():
    agent = _StopAfterStart(
        ExplodingLLM(), amap_client=None, poi_details=SitesStore()
    )
    session = run(
        agent.start(
            device_id="d1",
            cities=["上海"],
            days=3,
            preferences="Beijing, the Forbidden City and the Summer Palace",
            brief="Beijing, the Forbidden City and the Summer Palace",
        )
    )
    assert session.cities == ["北京"]
    assert session.days == 3


def test_start_keeps_form_route_when_brief_matches_it():
    agent = _StopAfterStart(
        ExplodingLLM(), amap_client=None, poi_details=SitesStore()
    )
    session = run(
        agent.start(
            device_id="d1",
            cities=["北京"],
            days=3,
            preferences="北京",
            brief="北京",
        )
    )
    assert session.cities == ["北京"]
    assert session.days == 3


# --- ③ 点名景点 → 必去 ----------------------------------------------------


def test_mine_brief_sites_reads_library_and_llm():
    store = SitesStore(
        rows_by_city={
            "北京": [
                {"name": "慕田峪长城", "city": "北京", "category": "nature"},
                {"name": "天坛", "city": "北京", "category": "temple"},
            ]
        },
        known={
            ("北京", "颐和园"): {
                "name": "颐和园",
                "city": "北京",
                "category": "park",
            }
        },
    )
    llm = ScriptedLLM([_sites_reply("颐和园")])
    agent = PlanningAgent(llm, amap_client=None, poi_details=store)
    session = _session()

    added, notes = run(agent._mine_brief_sites(session))

    # 文本顺序优先（LLM 读出的先后），底库独有项排在其后
    assert added == ["颐和园", "慕田峪长城", "天坛"]
    assert notes == []
    assert session.must_visits == ["颐和园", "慕田峪长城", "天坛"]
    assert session.site_kinds["颐和园"] == "sight"
    assert session.site_cities["颐和园"] == "北京"
    # 读的是那句话本身，不是品类 token
    assert store.match_calls and store.match_calls[0][1] == TEXT
    assert llm.system_prompts and "中文名" in llm.system_prompts[0]


def test_mine_brief_sites_follows_text_sequence_and_days():
    known = {
        ("北京", name): {"name": name, "city": "北京", "category": "sight"}
        for name in ("故宫博物院", "慕田峪长城", "天坛", "颐和园")
    }
    store = SitesStore(rows_by_city={"北京": []}, known=known)
    llm = ScriptedLLM(
        [
            _sites_reply(
                ("故宫博物院", 1),
                ("慕田峪长城", 1),
                ("天坛", 2),
                ("颐和园", 2),
            )
        ]
    )
    agent = PlanningAgent(llm, amap_client=None, poi_details=store)
    session = _session()

    added, _ = run(agent._mine_brief_sites(session))

    assert added == ["故宫博物院", "慕田峪长城", "天坛", "颐和园"]
    assert session.site_days == {
        "故宫博物院": 1,
        "慕田峪长城": 1,
        "天坛": 2,
        "颐和园": 2,
    }


def test_merge_must_visits_pins_the_day_written_in_the_text():
    store = SitesStore()
    agent = PlanningAgent(ExplodingLLM(), amap_client=None, poi_details=store)
    bindings = {
        name: {
            "name": name,
            "city": "北京",
            "category": "sight",
            "location": {"lon": 116.4, "lat": 39.9},
            "suggested_duration_min": 120,
        }
        for name in ("故宫博物院", "天坛")
    }

    specs = agent._merge_must_visits(
        [],
        ["故宫博物院", "天坛"],
        ["北京"],
        2,
        {"北京": (1, 2)},
        bindings=bindings,
        site_days={"故宫博物院": 2, "天坛": 1},
    )

    assert {spec["name"]: spec["day"] for spec in specs} == {
        "故宫博物院": 2,
        "天坛": 1,
    }


def test_mine_brief_sites_drops_unlocatable_llm_names():
    store = SitesStore(rows_by_city={"北京": []}, known={})
    llm = ScriptedLLM([_sites_reply("某不存在的观景台")])
    agent = PlanningAgent(llm, amap_client=None, poi_details=store)
    session = _session()

    added, notes = run(agent._mine_brief_sites(session))

    assert added == []
    assert session.must_visits == []
    assert notes and "某不存在的观景台" in notes[0]


def test_mine_brief_sites_skips_short_text_and_never_calls_llm():
    store = SitesStore(rows_by_city={"北京": [{"name": "天坛"}]})
    agent = PlanningAgent(ExplodingLLM(), amap_client=None, poi_details=store)
    session = _session(preferences="北京", brief_text="北京")

    added, notes = run(agent._mine_brief_sites(session))

    assert added == [] and notes == []
    assert session.must_visits == []
    assert store.match_calls == []


def test_mine_brief_sites_runs_once_per_session():
    store = SitesStore(
        rows_by_city={"北京": [{"name": "天坛", "city": "北京", "category": "temple"}]}
    )
    llm = ScriptedLLM([_sites_reply()])
    agent = PlanningAgent(llm, amap_client=None, poi_details=store)
    session = _session()

    first, _ = run(agent._mine_brief_sites(session))
    second, _ = run(agent._mine_brief_sites(session))

    assert first == ["天坛"]
    assert second == []
    assert llm.calls == 1
    assert session.must_visits == ["天坛"]


def test_mine_brief_sites_dedupes_against_wishlist_must_visits():
    store = SitesStore(
        rows_by_city={"北京": [{"name": "天坛", "city": "北京", "category": "temple"}]}
    )
    agent = PlanningAgent(
        ScriptedLLM([_sites_reply()]), amap_client=None, poi_details=store
    )
    session = _session(must_visits=["天坛"])

    added, _ = run(agent._mine_brief_sites(session))

    assert added == []
    assert session.must_visits == ["天坛"]


def test_mine_brief_sites_ignores_link_brief():
    store = SitesStore(rows_by_city={"北京": [{"name": "天坛"}]})
    agent = PlanningAgent(ExplodingLLM(), amap_client=None, poi_details=store)
    session = _session(
        brief_text="https://example.com/beijing-2-days " + "欣赏天坛和颐和园的秋色" * 3
    )

    added, notes = run(agent._mine_brief_sites(session))

    assert added == [] and notes == []
    assert store.match_calls == []


# --- ④ 文字/视频简报 → 用户确认 → 心愿单备排项（2026-11-14 用户拍板） -----


class _Recorder:
    """TripItemService 桩：只记 create 的入参。"""

    def __init__(self) -> None:
        self.created: list[tuple[str, dict]] = []

    def create(self, name, **kwargs):
        self.created.append((name, kwargs))
        return {"id": f"row-{len(self.created)}", "name": name}

    def list_groups(self, *args, **kwargs):
        return {"wishlist": [], "scheduled": []}


class _RoundOnly(PlanningAgent):
    """走真实 _brief_site_round（确认轮），不进生成管线。"""

    async def _generate_v0(self, session, *, extra_assumptions=None):
        await self._brief_site_round(session)
        return session


def _brief_store():
    rows = [
        {"name": "天坛", "city": "北京", "category": "temple"},
        {"name": "颐和园", "city": "北京", "category": "park"},
    ]
    return SitesStore(
        rows_by_city={"北京": rows},
        known={(r["city"], r["name"]): r for r in rows},
    )


def test_typed_brief_opens_confirm_round_before_any_write():
    recorder = _Recorder()
    agent = _RoundOnly(
        ScriptedLLM([_sites_reply()]),
        amap_client=None,
        poi_details=_brief_store(),
        trip_items=recorder,
    )

    session = run(
        agent.start(
            device_id="d1", cities=["北京"], days=2, preferences=TEXT, brief=TEXT
        )
    )

    assert session.state == "site_confirm"
    assert session.pending_sites == ["天坛", "颐和园"]
    assert session.pending_sites_source == "brief"
    assert session.must_visits == []
    assert session.plan is None
    assert recorder.created == []  # 没确认前一个都不入库
    assert "这些地点" in session.history[-1].content


def test_confirm_brief_round_writes_picked_only():
    recorder = _Recorder()
    agent = _RoundOnly(
        ScriptedLLM([_sites_reply()]),
        amap_client=None,
        poi_details=_brief_store(),
        trip_items=recorder,
    )
    session = run(
        agent.start(
            device_id="d1", cities=["北京"], days=2, preferences=TEXT, brief=TEXT
        )
    )

    session, reply, _ = run(agent.confirm_sites(session, ["天坛"]))

    assert [name for name, _ in recorder.created] == ["天坛"]
    assert recorder.created[0][1]["source"] == "chat"
    assert "文字/视频描述" in recorder.created[0][1]["note"]
    assert session.must_visits == ["天坛"]
    assert session.pending_sites == []
    assert session.pending_sites_source == "link"
    assert "未点选" in reply
    assert "你确认的" in reply


def test_brief_mining_without_commit_leaves_must_visits_empty():
    agent = _RoundOnly(
        ScriptedLLM([_sites_reply()]), amap_client=None, poi_details=_brief_store()
    )
    session = _session()

    first, _ = run(agent._mine_brief_sites(session, commit=False))
    assert first == ["天坛", "颐和园"]
    assert session.must_visits == []  # 只读点，不落库

    second, _ = run(agent._mine_brief_sites(session, commit=False))
    assert second == []  # 每会话只读一次


# --- ⑤ 图片读点（2026-11-14「图片上有的也抽出来」） -----------------------


class _VisionLLM(ScriptedLLM):
    """带 chat_vision 的桩：文字回复照旧，视觉调用返回图里的地点 JSON。"""

    name = "scripted+vision"

    def __init__(self, replies: list[str], vision_reply: str) -> None:
        super().__init__(replies)
        self.vision_reply = vision_reply
        self.vision_calls: list[int] = []

    async def chat_vision(self, images, prompt: str) -> str:
        self.vision_calls.append(len(images))
        return self.vision_reply


def test_image_round_reads_sites_and_waits_for_confirm():
    llm = _VisionLLM(
        [],
        json.dumps(
            {
                "sites": [
                    {"name": "天坛", "kind": "sight", "city": "北京"},
                    {"name": "不存在的观景台", "kind": "sight", "city": "北京"},
                ]
            },
            ensure_ascii=False,
        ),
    )
    recorder = _Recorder()
    agent = PlanningAgent(
        llm,
        amap_client=None,
        poi_details=_brief_store(),
        trip_items=recorder,
    )
    session = _session()

    session, reply = run(agent.image_site_round(session, [(b"img", "image/jpeg")]))

    assert llm.vision_calls == [1]
    assert session.state == "site_confirm"
    assert session.pending_sites == ["天坛"]
    assert session.pending_sites_source == "image"
    assert session.site_cities["天坛"] == "北京"
    assert recorder.created == []  # 确认前不入库
    assert "图片里" in reply and "不存在的观景台" in reply


def test_image_round_merges_into_open_round():
    llm = _VisionLLM(
        [],
        json.dumps(
            {"sites": [{"name": "天坛", "kind": "sight", "city": "北京"}]},
            ensure_ascii=False,
        ),
    )
    agent = PlanningAgent(llm, amap_client=None, poi_details=_brief_store())
    session = _session(state="site_confirm", pending_sites=["颐和园"])

    session, _ = run(agent.image_site_round(session, [(b"img", "image/jpeg")]))

    assert session.pending_sites == ["颐和园", "天坛"]


def test_confirm_after_image_round_writes_picked_row():
    llm = _VisionLLM(
        [],
        json.dumps(
            {"sites": [{"name": "天坛", "kind": "sight", "city": "北京"}]},
            ensure_ascii=False,
        ),
    )
    recorder = _Recorder()
    agent = _RoundOnly(
        llm, amap_client=None, poi_details=_brief_store(), trip_items=recorder
    )
    # 只走图片轮：短偏好不进文字读点（_MIN_BRIEF_TEXT 内），避免串到 brief 轮
    session = _session(preferences="北京", brief_text="")

    session, _ = run(agent.image_site_round(session, [(b"img", "image/jpeg")]))
    session, reply, _ = run(agent.confirm_sites(session, ["天坛"]))

    assert [name for name, _ in recorder.created] == ["天坛"]
    assert recorder.created[0][1]["source"] == "chat"
    assert "图片" in recorder.created[0][1]["note"]
    assert "你确认的" in reply
