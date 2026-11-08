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

2026-11-08 长恨歌案四刀之三落在本文件（终装侧）：
⑤停演季闸——opening_hours 含「演出季X-Y月/冬季停演」窄模式且行程月
  与演出季全无交集 → 该夜场退出自动收尾桶+披露，选择落到下一张在季
  演出（室内替代）；
⑥演出日按最近簇选日——夜场不再盲钉窗口末日，某天已有点距场馆
  ≤5km（_NEAR_SAMEDAY_KM）时演出改钉该天（同址 0km 必须同日）；
⑦夜场桶落选张（shows[1:]）不再无痕消失——日志+披露点名；
⑨⑩场馆亲和护栏（2026-11-08 秦俑情案第五刀）——评分器拆簇软罚
  （venue_strand）+ LNS 演出软钉：重排/挪天家族不得把贴场馆簇的
  演出挪去无锚日，容量溢出让弱卡让位。
"""

import asyncio
from datetime import time

from app.services.agent.plan import PlanningAgent
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    VisitItem,
)
from app.services.itinerary.scoring import PEN_VENUE_STRAND, plan_score
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


def _night_show(name, lon, lat, *, dur=80, hours="19:30-21:00"):
    """仅夜场演出（opening_hours 无「多场/全天/日场」→ 晚档收尾桶）。"""
    return {
        "name": name,
        "city": "西安",
        "category": "entertainment",
        "best_visit_time": "show",
        "opening_hours": hours,
        "location": {"lon": lon, "lat": lat},
        "suggested_duration_min": dur,
    }


def _placed(
    item_id, name, day, lon, lat, dur, *, start=None, show=False, category=None
):
    """已落位 VisitItem（第五刀回归锚用）：start 给小时即有起止时刻，
    缺省=无时刻卡；show=True 走演出口径（entertainment+多场次）。"""
    st = time(start, 0) if start is not None else None
    en = None
    if st is not None:
        m = st.hour * 60 + st.minute + dur
        en = time(m // 60, m % 60)
    return VisitItem(
        item_id=item_id,
        name=name,
        category=("entertainment" if show else (category or "sight")),
        best_visit_time=("show" if show else "any"),
        city="西安",
        day=day,
        duration_minutes=dur,
        location=GeoPoint(lon=lon, lat=lat),
        start_time=st,
        end_time=en,
        opening_hours=("多场（约11:00/14:00/17:00）" if show else None),
    )


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


# ---------- 2026-11-08 长恨歌案：停演季闸 / 最近簇选日 / 落选张披露 ----------

_chg_hours = "仅夜场（约20:10/21:35两场；演出季4-10月，冬季停演）"


def test_night_show_off_season_skipped_with_disclosure():
    # ⑥停演季闸：11 月行程撞「演出季4-10月」停演期——《长恨歌》退出
    # 自动夜场桶并披露；选择自然落到下一张在季演出《梦回大唐》。
    cands = [
        _sight("兵马俑", *_LINTONG, dur=90, tags=["5a"]),
        _night_show("《长恨歌》", *_LINTONG, hours=_chg_hours),
        _night_show("《梦回大唐》", *_DOWNTOWN),
    ]
    notes: list[str] = []
    items = PlanningAgent._deterministic_selection(
        cands, 2, {"西安": (1, 2)}, notes=notes, start_date="2026-11-10"
    )
    names = [it["name"] for it in items]
    assert "《长恨歌》" not in names  # 停演期退出自动夜场桶
    assert "《梦回大唐》" in names  # 落到下一张在季演出
    assert any("演出季4-10月" in n and "停演" in n and "《长恨歌》" in n for n in notes)


def test_night_show_season_spanning_trip_not_blocked():
    # ⑥防误伤：跨季行程（10月末起）与演出季 4-10 月有交集 → 照排不拦。
    cands = [_night_show("《长恨歌》", *_LINTONG, hours=_chg_hours)]
    items = PlanningAgent._deterministic_selection(
        cands, 2, {"西安": (1, 2)}, start_date="2026-10-31"
    )
    assert [it["name"] for it in items] == ["《长恨歌》"]


def test_night_show_follows_same_site_daytime_cluster():
    # ⑦最近簇选日：末日逢雨把同址白天点（华清宫，露天）钉去 day1，夜场
    # 不再盲钉窗口末日——按最近簇选日改钉 day1，同址 0km 必须同日。
    cands = [
        _sight("华清宫", *_LINTONG, dur=120, rain_ok="no"),
        _night_show("《长恨歌》", *_LINTONG),
    ]
    items = PlanningAgent._deterministic_selection(
        cands, 3, {"西安": (1, 3)}, rain_days={"西安": {3}}
    )
    day_of = {it["name"]: it["day"] for it in items}
    assert day_of["华清宫"] == 1  # 末日逢雨：露天点去 day1（拉日圈失效）
    assert day_of["《长恨歌》"] == 1  # 演出日反向拉到白天簇（同址同日）


def test_extra_night_shows_disclosed_not_silent():
    # ⑧落选张披露：每城夜场桶只排第一张，shows[1:] 不再无痕消失。
    cands = [
        _sight("兵马俑", *_LINTONG, dur=90, tags=["5a"]),
        _night_show("《长恨歌》", *_LINTONG),
        _night_show("《梦回大唐》", *_DOWNTOWN),
    ]
    notes: list[str] = []
    items = PlanningAgent._deterministic_selection(
        cands, 2, {"西安": (1, 2)}, notes=notes
    )
    names = [it["name"] for it in items]
    assert "《长恨歌》" in names  # 池序第一张当选
    assert "《梦回大唐》" not in names  # 同档落选
    assert any(
        "夜场演出仅自动排一场" in n and "《长恨歌》" in n and "《梦回大唐》" in n
        for n in notes
    )


def test_plan_score_penalizes_show_stranded_from_venue_cluster():
    # ⑨场馆亲和拆簇罚（E2E 5月探针实录）：《秦俑情》被「跨天全局重排」
    # 挪去市区日、兵马俑留临潼日=双件拆离场馆簇——55km 脱簇在 travel 软项
    # 只值 -2 拦不住；同日贴排（0.95km 成伴）不罚。
    bmy = _placed(
        "v-bmy", "兵马俑", 2, 109.27, 34.38, 180, start=9, category="attraction"
    )
    qyq = _placed("v-qyq", "《秦俑情》", 2, 109.278, 34.384, 80, start=17, show=True)
    hms = _placed("v-hms", "回民街", 1, 108.94, 34.26, 90, start=9)
    home = ItineraryPlan(
        itinerary_id="it-home",
        cities=["西安"],
        days=[
            DayPlan(day=1, base_city="西安", items=[hms]),
            DayPlan(day=2, base_city="西安", items=[bmy, qyq]),
        ],
    )
    stranded = ItineraryPlan(
        itinerary_id="it-strand",
        cities=["西安"],
        days=[
            DayPlan(
                day=1,
                base_city="西安",
                items=[hms, qyq.model_copy(update={"day": 1})],
            ),
            DayPlan(day=2, base_city="西安", items=[bmy]),
        ],
    )
    assert plan_score(home).soft["venue_strand"] == 0
    assert plan_score(stranded).soft["venue_strand"] == -2 * PEN_VENUE_STRAND


def test_lns_keeps_day_show_with_overloaded_venue_cluster():
    # ⑩场馆亲和软钉（秦俑情案第五刀主锚）：临潼日=兵马俑180+华清宫120+
    # 骊山60+秦俑情80 超载排不下——修复通道不得把贴兵马俑（~1km）的
    # 《秦俑情》挪去市区日：演出软钉不挪；要让位/拆日重建也是弱卡让，
    # 兵马俑锚点同守（venue_strand 罚管另一侧拆簇）。
    agent = PlanningAgent(NoLLM())
    day1 = DayPlan(
        day=1,
        base_city="西安",
        items=[
            _placed("v-hms", "回民街", 1, 108.94, 34.26, 90, start=9),
            _placed("v-dyt", "大雁塔", 1, 108.96, 34.22, 90, start=14),
        ],
    )
    day2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            _placed(
                "v-bmy", "兵马俑", 2, 109.27, 34.38, 180, start=9, category="attraction"
            ),
            _placed(
                "v-hqg",
                "华清宫",
                2,
                109.212,
                34.366,
                120,
                start=14,
                category="attraction",
            ),
            _placed("v-lsh", "骊山", 2, 109.217, 34.365, 60),
            _placed("v-qyq", "《秦俑情》", 2, 109.278, 34.384, 80, show=True),
        ],
    )
    plan = ItineraryPlan(itinerary_id="it1", cities=["西安"], days=[day1, day2])
    picked = [
        {"name": n}
        for n in ("回民街", "大雁塔", "兵马俑", "华清宫", "骊山", "《秦俑情》")
    ]

    moves, base_s, final_s = agent._global_resched(plan, picked, [])

    assert final_s > base_s  # 超载信号确有修复
    all_items = [i for d in plan.days for i in d.items if isinstance(i, VisitItem)]
    qyq_it = next(i for i in all_items if i.name == "《秦俑情》")
    bmy_it = next(i for i in all_items if i.name == "兵马俑")
    assert qyq_it.day == 2  # 演出不挪——必须贴兵马俑线路
    assert bmy_it.day == 2  # 锚点同守——不从另一侧拆簇
    assert all("秦俑情" not in m for m in moves)  # 披露不得点名演出挪动
