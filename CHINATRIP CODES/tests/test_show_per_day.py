# -*- coding: utf-8 -*-
"""演出每场闸（2026-11-02 用户拍板「一天最多一场演出」）。

线上会话 c47b2569（上海→西安→上海 5 天，start 11-02）：day2 常规选点
已排《秦俑情》（多场次下午场演出→普通观光桶），雨天对调③又把未入选
的室内演出《复活的军团》顶上——同天两场演出。本组锁：
①选点主闸——全通道落位收口后按天清点，第二场演出按池序裁掉并披露；
②夜场收尾联动——收尾日已有演出改钉窗口内最近无演出日，全窗都有演出
  则不重复钉；
③雨天替补可用演出——①/②/③段与夜间窗对调按原口径取室内候选
  （2026-11-02 用户更正：并未要求剔除演出），同天重复由主闸裁并；
④均衡回填联动——已有演出的一天不补第二场演出。
"""

import asyncio

from app.services.agent.plan import PlanningAgent
from app.services.poi_details import PoiDetailStore


def run(coro):
    return asyncio.run(coro)


class NoLLM:
    """候选闸不需要 LLM；任何调用都是测试哨兵。"""

    name = "no-llm"

    async def chat(self, messages, *, temperature: float = 0.3, max_tokens=None):
        raise AssertionError("candidate gate must not call the LLM")


_LINTONG = (109.27, 34.38)  # 临潼簇（共址控腿=0）
_DOWNTOWN = (108.95, 34.27)  # 市区簇（与临潼 ~30km 拉开成第二簇）


def _sight(name, lon, lat, *, dur=120, tags=None, rain_ok=None):
    c = {
        "name": name,
        "city": "西安",
        "category": "sight",
        "location": {"lon": lon, "lat": lat},
        "suggested_duration_min": dur,
    }
    if tags is not None:
        c["tags"] = tags
    if rain_ok is not None:
        c["rain_ok"] = rain_ok
    return c


def _day_show(name, lon, lat, *, dur=80):
    """多场次白天演出：opening_hours 含「多场」→ 普通观光桶（非仅夜场），
    _cand_is_show 走 best_visit_time=show。"""
    return {
        "name": name,
        "city": "西安",
        "category": "sight",
        "best_visit_time": "show",
        "opening_hours": "多场 11:00/14:00/17:00",
        "rain_ok": "yes",
        "location": {"lon": lon, "lat": lat},
        "suggested_duration_min": dur,
    }


def _night_show(name, lon, lat, *, dur=80):
    """仅夜场演出（opening_hours 无「多场/全天/日场」→ 晚档收尾桶）。"""
    return {
        "name": name,
        "city": "西安",
        "category": "entertainment",
        "best_visit_time": "show",
        "opening_hours": "19:30-21:00",
        "location": {"lon": lon, "lat": lat},
        "suggested_duration_min": dur,
    }


def test_gate_keeps_one_show_per_day_disclosed():
    cands = [
        _sight("兵马俑", *_LINTONG, dur=90, tags=["5a"]),
        _day_show("《秦俑情》", *_LINTONG),
        _day_show("《复活的军团》", *_LINTONG),
    ]
    notes: list[str] = []
    items = PlanningAgent._deterministic_selection(
        cands, 1, {"西安": (1, 1)}, notes=notes
    )
    names = [it["name"] for it in items]
    assert "兵马俑" in names and "《秦俑情》" in names
    assert "《复活的军团》" not in names  # 同天第二场按池序裁掉
    assert any("一天只排一场演出" in n and "《复活的军团》" in n for n in notes)


def test_night_finale_skipped_when_single_day_already_has_show():
    cands = [
        _day_show("《秦俑情》", *_LINTONG),
        _night_show("《梦回大唐》", *_LINTONG),
    ]
    notes: list[str] = []
    items = PlanningAgent._deterministic_selection(
        cands, 1, {"西安": (1, 1)}, notes=notes
    )
    names = [it["name"] for it in items]
    assert "《秦俑情》" in names
    assert "《梦回大唐》" not in names  # 全窗都有演出 → 夜场不重复钉
    assert any("《梦回大唐》" in n and "不重复排" in n for n in notes)


def test_night_finale_moves_to_show_free_day():
    cands = [
        _sight("兵马俑", *_LINTONG, dur=120, tags=["5a"]),
        _sight("钟楼", *_DOWNTOWN, dur=120),
        _day_show("《秦俑情》", *_DOWNTOWN),
        _night_show("《梦回大唐》", *_DOWNTOWN),
    ]
    items = PlanningAgent._deterministic_selection(cands, 2, {"西安": (1, 2)})
    day_of = {}
    for it in items:
        day_of.setdefault(it["name"], it["day"])
    # 簇 rank：临潼有 5a → day1；市区簇 → day2。day2 已有白天演出 →
    # 夜场收尾改钉无演出日 day1。
    assert day_of["《秦俑情》"] == 2
    assert day_of["《梦回大唐》"] == 1


def test_rain_rescue_may_use_show_and_cap_keeps_one_per_day():
    # 2026-11-02 用户更正：雨天替补不剔除演出。复刻同形态：雨日
    # 兵马俑90+秦俑情80+华清池120=290，复活的军团 290+80>360 溢出干日
    # day2；华清池（露天）被雨控 → ①用干日室内演出《复活的军团》对调
    # （华清池去干日、演出来雨日）→ 主闸裁掉同天第二场《复活的军团》。
    # 终态：day1=兵马俑+秦俑情（1 场），day2=华清池（干日）。
    cands = [
        _sight("兵马俑", *_LINTONG, dur=90, tags=["5a"], rain_ok="yes"),
        _day_show("《秦俑情》", *_LINTONG),
        _sight("华清池", *_LINTONG, dur=120, rain_ok="no"),
        _day_show("《复活的军团》", *_LINTONG),
    ]
    notes: list[str] = []
    items = PlanningAgent._deterministic_selection(
        cands, 2, {"西安": (1, 2)}, rain_days={"西安": {1}}, notes=notes
    )
    day_of = {}
    for it in items:
        day_of.setdefault(it["name"], it["day"])
        shows_on_day = [
            x for x in items if x["day"] == it["day"] and x["name"].startswith("《")
        ]
        assert len(shows_on_day) <= 1, "同天两场演出：%r" % shows_on_day
    assert day_of["华清池"] == 2  # 演出替补生效：露天点换去干日
    assert day_of["《秦俑情》"] == 1
    assert "《复活的军团》" not in day_of  # 同天第二场被主闸裁掉
    assert any(
        "一天只排一场演出" in n and "《复活的军团》" in n for n in notes
    )  # 无论华清池走初排溢出还是替补路径，同天不重都由主闸保证


def test_rebalance_refill_skips_show_on_day_that_has_one():
    picked = [
        {
            "name": "《秦俑情》",
            "city": "西安",
            "category": "entertainment",
            "day": 1,
            "duration_minutes": 80,
            "location": {"lon": 109.27, "lat": 34.38},
        }
    ]
    cands = [
        {
            "name": "《复活的军团》",
            "city": "西安",
            "category": "entertainment",
            "best_visit_time": "show",
            "opening_hours": "多场 11:00/17:00",
            "suggested_duration_min": 80,
            "location": {"lon": 109.27, "lat": 34.38},
        }
    ]
    new_picked, _notes = PlanningAgent._rebalance_days(
        picked, cands, 1, {"西安": (1, 1)}
    )
    assert [p["name"] for p in new_picked] == ["《秦俑情》"]


def test_collect_candidates_reserves_show_rows_outside_window():
    # 复刻 2026-11-02 西安实录：坐标回填把大量普通行补齐坐标后，无评分
    # 演出行被挤出 top-30 窗口（实录排 40-53 位全灭、新计划零演出）——
    # 窗口满员时同城窗口外保底最多 3 行有坐标演出。
    store = PoiDetailStore()
    for i in range(30):
        store.upsert(
            "F%02d" % i,
            city="西安",
            name="普通点%02d" % i,
            category="attraction",
            location=(108.9 + i * 0.001, 34.2),
            rating=4.8,
            rating_count=1000,
        )
    for j, nm in enumerate(
        ("《梦回大唐》", "《秦俑情》", "《复活的军团》", "《驼铃传奇》秀")
    ):
        store.upsert(
            "SH%d" % j,
            city="西安",
            name=nm,
            category="entertainment",
            source="show",
            location=(109.0 + j * 0.01, 34.3),
        )
    agent = PlanningAgent(NoLLM(), amap_client=None, poi_details=store)
    candidates, _ = run(agent._collect_candidates(["西安"]))
    show_names = [c["name"] for c in candidates if c["name"].startswith("《")]
    assert len(show_names) == 3  # 保位上限 3：第 4 行演出不进池
    assert "《驼铃传奇》秀" not in show_names
