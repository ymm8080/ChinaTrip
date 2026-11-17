# -*- coding: utf-8 -*-
"""LLM 先读懂用户原句（2026-11-17 用户拍板「WE SHOULD HV LLM UNDERSTAND
DATE, TIME DURATION ETC THEN INPUT INFORMATION INTO OUR PLANNING ENGINE」）。

真实会话 fc573cde：preferences=
「I WANT TO GO TO ZHUJIAZUI ON DEC.02.  LEAVE HOTEL ON 11AM, PLS ARRANGE」
此前连环弹窗——英文日期读不出 → 行前卡；文字折进 preferences 而城市空 →
clarify 追问目的地。口径：
① LLM trip_facts 读句出 {city, start_date, days, day1_start} 直接灌引擎
   （白名单/ISO/1-30 天/HH:MM 校验）；正则只在 LLM 读不出时兜底；
② 只写一个日期 = 一日游（IT MEANS ONLY ONE DAY TRIP）；
③ 城市按点名景点反推（WE SHOULD FILTER OUT CITY ACCORDING TO SITES
   NAME）——同名分布在多城 = 歧义不猜；拼写误差（ZHUJIAZUI）由 LLM 纠；
④ 「LEAVE HOTEL ON 11AM」= 第 1 天出发时刻，v0 落位不建交通腿。
"""

import asyncio
import json
from datetime import date, time

from app.services.agent.plan import (
    PlanningAgent,
    PlanSession,
    _count_text_dates,
    _parse_text_day_start,
    _parse_text_start_date,
)
from app.services.itinerary import DayPlan, ItineraryPlan, VisitItem
from app.services.llm.base import ChatResult
from app.services.poi_details import PoiDetailStore

COMMENT = (
    "I WANT TO GO TO ZHUJIAZUI ON DEC.02.  LEAVE HOTEL ON 11AM, PLS ARRANGE"
)


class ScriptedLLM:
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


class CommentStore(PoiDetailStore):
    """底库桩：全局/按城 match + 同名城市分布 + 精确绑定。"""

    def __init__(self) -> None:
        super().__init__()
        self.match_calls: list[tuple] = []
        self.spread_map = {"朱家角古镇": ["上海"], "中山公园": ["上海", "北京"]}
        self.known = {
            (None, "朱家角古镇"): {
                "name": "朱家角古镇",
                "city": "上海",
                "category": "sight",
            },
            ("上海", "朱家角古镇"): {
                "name": "朱家角古镇",
                "city": "上海",
                "category": "sight",
            },
        }

    def match_text_names(self, city, text, *, limit=8):
        self.match_calls.append((city, text))
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
        if "zhongshan" in low or "中山公园" in (text or ""):
            return [
                {
                    "name": "中山公园",
                    "name_en": "Zhongshan Park",
                    "city": "上海",
                    "category": "park",
                }
            ]
        return []

    def candidate_by_name(self, city, name):
        return self.known.get((city, name))

    def name_city_spread(self, name):
        return list(self.spread_map.get(name, []))


def _sites_reply(name: str, city: str = "上海") -> str:
    return json.dumps(
        {"sites": [{"name": name, "kind": "sight", "city": city, "day": 0}]},
        ensure_ascii=False,
    )


def _facts_reply(**kw) -> str:
    payload = {
        "city": None,
        "start_date": None,
        "days": None,
        "day1_start": None,
    }
    payload.update(kw)
    return json.dumps(payload, ensure_ascii=False)


def _dec2() -> str:
    """Dec 02 of the current year, rolling over after it passes."""
    today = date.today()
    year = today.year if (today.month, today.day) < (12, 2) else today.year + 1
    return f"{year}-12-02"


# --- ① LLM 事实读取 --------------------------------------------------------


def test_trip_facts_from_llm_extracts_and_validates():
    llm = ScriptedLLM(
        [_facts_reply(city="上海", start_date=_dec2(), days=1, day1_start="11:00")]
    )
    agent = PlanningAgent(llm, amap_client=None, poi_details=CommentStore())
    facts = asyncio.run(agent.trip_facts_from_llm(COMMENT))
    assert facts == {
        "city": "上海",
        "start_date": _dec2(),
        "days": 1,
        "day1_start": "11:00",
    }


def test_trip_facts_from_llm_drops_invalid_fields():
    llm = ScriptedLLM(
        [
            _facts_reply(
                city="NotACity", start_date="bad", days=99, day1_start="25:00"
            )
        ]
    )
    agent = PlanningAgent(llm, amap_client=None, poi_details=CommentStore())
    assert asyncio.run(agent.trip_facts_from_llm(COMMENT)) is None


def test_trip_facts_from_llm_guards():
    agent = PlanningAgent(None, amap_client=None, poi_details=CommentStore())
    assert asyncio.run(agent.trip_facts_from_llm(COMMENT)) is None
    llm = ScriptedLLM([])
    agent = PlanningAgent(llm, amap_client=None, poi_details=CommentStore())
    assert asyncio.run(agent.trip_facts_from_llm("short")) is None


# --- ② 正则兜底（LLM 不可用时） ---------------------------------------------


def test_parse_text_start_date_english_months():
    assert _parse_text_start_date("I want to go on DEC.02.") == _dec2()
    assert _parse_text_start_date("Trip on Dec 2nd please") == _dec2()
    assert _parse_text_start_date("2nd December works") == _dec2()
    assert _parse_text_start_date("December 2 is fine") == _dec2()
    assert _parse_text_start_date("how about dec02 then") == _dec2()
    # 年份词不是日；没有日期读 None（原口径不变）
    assert _parse_text_start_date("may 2026 hold") is None
    assert _parse_text_start_date("no dates here") is None
    assert _parse_text_start_date("11月20日出发") is not None


def test_count_text_dates_single_vs_range():
    assert _count_text_dates("on DEC.02 only") == 1
    assert _count_text_dates("trip from Nov 20 to Nov 22") == 2
    assert _count_text_dates("11月20日到11月22日") == 2
    assert _count_text_dates("2026-12-02") == 1
    assert _count_text_dates("plain words, no dates") == 0


def test_parse_text_day_start_variants():
    assert _parse_text_day_start(COMMENT) == "11:00"
    assert _parse_text_day_start("9点出发") == "09:00"
    assert _parse_text_day_start("上午10:30退房") == "10:30"
    assert _parse_text_day_start("leaving around 2pm from the hotel") == "14:00"
    # 日期词不是时刻；没提时间不给
    assert _parse_text_day_start("12月2日出发") is None
    assert _parse_text_day_start("no time mentioned at all") is None


def test_parse_days_ignores_clock_times():
    # 「LEAVE HOTEL ON 11AM」裸数字兜底曾读成 11 天——时刻要先掩掉
    from app.services.agent.plan import _parse_days

    assert _parse_days(COMMENT) is None
    assert _parse_days("meet at 10:30am for 2 days") == 2


# --- ③ 城市按点名景点反推 --------------------------------------------------


def test_city_from_text_sites_unique_name():
    agent = PlanningAgent(None, amap_client=None, poi_details=CommentStore())
    city = asyncio.run(
        agent._city_from_text_sites("I want to go to Zhujiajiao please")
    )
    assert city == "上海"


def test_city_from_text_sites_ambiguous_name_across_cities():
    agent = PlanningAgent(None, amap_client=None, poi_details=CommentStore())
    city = asyncio.run(agent._city_from_text_sites("visit Zhongshan Park"))
    assert city is None  # 同名分布多城：歧义，不猜


def test_city_from_text_sites_llm_repairs_typo():
    # ZHUJIAZUI 库名不含——LLM 读句出规范中文名再全局绑定
    llm = ScriptedLLM([_sites_reply("朱家角古镇")])
    agent = PlanningAgent(llm, amap_client=None, poi_details=CommentStore())
    city = asyncio.run(agent._city_from_text_sites(COMMENT))
    assert city == "上海"
    assert llm.calls == 1


# --- start()：LLM 读句灌引擎，不再连环弹窗 ----------------------------------


def test_start_understands_comment_without_clarify():
    # 拍板①：LLM 一次读出事实灌进会话（城市/日期/天数/出发时刻）
    llm = ScriptedLLM(
        [
            _facts_reply(
                city="上海", start_date=_dec2(), days=1, day1_start="11:00"
            ),
            _sites_reply("朱家角古镇"),
        ]
    )
    agent = PlanningAgent(llm, amap_client=None, poi_details=CommentStore())
    session = asyncio.run(
        agent.start(device_id="d1", cities=[], days=0, preferences=COMMENT)
    )
    assert session.state == "site_confirm"  # 不再 clarify
    assert session.cities == ["上海"]
    assert session.days == 1  # 单日期 = 一日游
    assert session.start_date == _dec2()
    assert session.comment_day_start == "11:00"
    assert session.pending_sites == ["朱家角古镇"]


def test_start_regex_fallback_when_llm_silent():
    # LLM 读不出事实时正则兜底（Dec.02/单日期=1/11AM）；城市走点名景点
    # 反推通道（读点 LLM 一次 + 挖点 LLM 一次）
    llm = ScriptedLLM(
        [_facts_reply(), _sites_reply("朱家角古镇"), _sites_reply("朱家角古镇")]
    )
    agent = PlanningAgent(llm, amap_client=None, poi_details=CommentStore())
    session = asyncio.run(
        agent.start(device_id="d1", cities=[], days=0, preferences=COMMENT)
    )
    assert session.cities == ["上海"]  # 走了点名景点反推通道
    assert session.days == 1
    assert session.start_date == _dec2()
    assert session.comment_day_start == "11:00"


def test_start_does_not_override_form_facts():
    # 表单/行前卡已有字段一律不覆盖（纯补空）
    agent = PlanningAgent(None, amap_client=None, poi_details=CommentStore())
    session = asyncio.run(
        agent.start(
            device_id="d1",
            cities=["北京"],
            days=3,
            start_date="2026-12-05",
            preferences=COMMENT,
        )
    )
    assert session.cities == ["北京"]
    assert session.days == 3
    assert session.start_date == "2026-12-05"


# --- ④ day-1 出发时刻落位 ---------------------------------------------------


def _mini_plan() -> ItineraryPlan:
    return ItineraryPlan(
        itinerary_id="it-x",
        cities=["上海"],
        days=[
            DayPlan(
                day=1,
                base_city="上海",
                items=[
                    VisitItem(
                        item_id="v1",
                        name="朱家角古镇",
                        city="上海",
                        category="sight",
                        day=1,
                        duration_minutes=90,
                        start_time=time(8, 30),
                        end_time=time(10, 0),
                    )
                ],
            )
        ],
    )


def test_apply_comment_day_start_retimes_first_visit():
    agent = PlanningAgent(None, amap_client=None, poi_details=CommentStore())
    session = PlanSession(
        session_id="s1", device_id="d1", cities=["上海"], days=1
    )
    session.plan = _mini_plan()
    session.comment_day_start = "11:00"
    notes = agent._apply_comment_day_start(session)
    visit = session.plan.days[0].items[0]
    assert visit.start_time == time(11, 0)
    assert notes and "11:00" in notes[0]
    assert session.comment_day_start is None  # 落位一次为止


def test_apply_comment_day_start_no_target_no_op():
    agent = PlanningAgent(None, amap_client=None, poi_details=CommentStore())
    session = PlanSession(
        session_id="s2", device_id="d1", cities=["上海"], days=1
    )
    session.plan = ItineraryPlan(
        itinerary_id="it-y",
        cities=["上海"],
        days=[DayPlan(day=1, base_city="上海", items=[])],
    )
    session.comment_day_start = "11:00"
    assert agent._apply_comment_day_start(session) == []
