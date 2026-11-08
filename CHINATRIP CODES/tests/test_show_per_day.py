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
⑦夜场桶落选张（shows[1:]）不再无痕消失——2026-11-08 二拍升级：落选张
  逐张落位（各按自场馆最近簇/无演出日，每天一场仍守），全窗无位才披露；
⑨⑩场馆亲和护栏（2026-11-08 秦俑情案第五刀）——评分器拆簇软罚
  （venue_strand）+ LNS 演出软钉：重排/挪天家族不得把贴场馆簇的
  演出挪去无锚日，容量溢出让弱卡让位。

2026-11-08 唐宴案三拍（终装侧）：
⑪宴秀占场——curated 宴会（唐宴/御宴宫，food+宴秀语素）本身就是当日
  那场「show」：同日不得再叠演出/第二场宴秀，宴秀留场优先并披露；
⑫认领避宴日——聚簇认领不得把演出认领进宴日（唐乐宫被「贴同日」
  认领进 D2 唐宴日实录）；换座（_reunite）同样双侧避宴日；
⑬就近留场——同日多场竞争按距当日簇最近 tiebreak（梦回大唐 0km 留、
  唐乐宫 12km 让；旧口径按在册序会留错的那个）；
⑭挤兑救援（四拍）——挪位后仍无时刻待删的强锚演出（全程任一日有
  ≤5km 场馆伴）与同城占席弱锚演出换位：强锚顶上晚位、弱锚承接
  死亡（梦回大唐 0km 贴芙蓉园顶掉 7km 无强锚唐乐宫）。
"""

import asyncio
from datetime import time

from app.services.agent.plan import (
    PlanningAgent,
    _enforce_show_per_day,
    _is_show_banquet_item,
    _is_show_item,
)
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


def test_extra_night_shows_all_placed_one_per_day():
    # ⑧二拍（2026-11-08 用户拍板：取消「每城只自动排一场夜场」）：两张
    # 夜场各落一天——每天一场仍守（11-02 拍板），落选张不再只披露不排。
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
    day_of = {it["name"]: it["day"] for it in items}
    assert "《长恨歌》" in names and "《梦回大唐》" in names
    assert day_of["《长恨歌》"] != day_of["《梦回大唐》"]  # 一天一场闸
    assert day_of["《长恨歌》"] == day_of["兵马俑"]  # 落位贴最近簇（同址同日）
    assert not any("未排" in n for n in notes)  # 都排下了：无未排披露


def test_extra_night_shows_disclosed_when_window_full():
    # ⑧二拍配套：三张夜场挤两天窗口——每天一场守闸，第三张点名披露
    # （要保留请说），不静默消失。
    cands = [
        _sight("兵马俑", *_LINTONG, dur=90, tags=["5a"]),
        _night_show("《长恨歌》", *_LINTONG),
        _night_show("《梦回大唐》", *_DOWNTOWN),
        _night_show("《驼铃传奇》秀", *_DOWNTOWN),
    ]
    notes: list[str] = []
    items = PlanningAgent._deterministic_selection(
        cands, 2, {"西安": (1, 2)}, notes=notes
    )
    names = [it["name"] for it in items]
    shows_placed = [n for n in names if n.startswith("《") or n.endswith("秀")]
    assert "《长恨歌》" in names and "《梦回大唐》" in names  # 每天一场=两张
    assert "《驼铃传奇》秀" not in names  # 第三张无日可落
    assert len(shows_placed) == 2
    assert any("未排" in n and "《驼铃传奇》秀" in n for n in notes)


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


def test_gate_reclaims_show_to_near_mate_day():
    # ⑧二拍聚簇认领（mc2 多城案实录）：选层把《秦俑情》落在市区无伴日、
    # 兵马俑在另一无演出日——终装闸把演出挪回伴的日子（贴排口径），并
    # 披露「贴同日改排」；挪后兜底重排给出时刻。
    qyq = _placed("v-qyq", "《秦俑情》", 1, 109.278, 34.384, 80, start=17, show=True)
    hms = _placed("v-hms", "回民街", 1, 108.94, 34.26, 90, start=9)
    bmy = _placed(
        "v-bmy", "兵马俑", 2, 109.27, 34.38, 180, start=9, category="attraction"
    )
    plan = ItineraryPlan(
        itinerary_id="it-mc2",
        cities=["西安"],
        days=[
            DayPlan(day=1, base_city="西安", items=[hms, qyq]),
            DayPlan(day=2, base_city="西安", items=[bmy]),
        ],
    )
    _enforce_show_per_day(plan)
    qyq_it = next(
        i for d in plan.days for i in d.items if getattr(i, "name", "") == "《秦俑情》"
    )
    bmy_it = next(
        i for d in plan.days for i in d.items if getattr(i, "name", "") == "兵马俑"
    )
    assert qyq_it.day == 2 and bmy_it.day == 2  # 演出挪回兵马俑日（~1km 伴）
    assert qyq_it.start_time is not None  # 挪后兜底重排有时刻
    assert any("秦俑情" in str(a) and "同日" in str(a) for a in plan.assumptions)


def test_gate_noop_leaves_compliant_plan_untouched():
    # 闸未动作零副作用：每天已一场且都贴簇 → 假设零新增、时刻不被重洗。
    bmy = _placed(
        "v-bmy", "兵马俑", 1, 109.27, 34.38, 180, start=9, category="attraction"
    )
    qyq = _placed("v-qyq", "《秦俑情》", 1, 109.278, 34.384, 80, start=17, show=True)
    hms = _placed("v-hms", "回民街", 2, 108.94, 34.26, 90, start=9)
    plan = ItineraryPlan(
        itinerary_id="it-ok",
        cities=["西安"],
        days=[
            DayPlan(day=1, base_city="西安", items=[bmy, qyq]),
            DayPlan(day=2, base_city="西安", items=[hms]),
        ],
    )
    _enforce_show_per_day(plan)
    assert plan.assumptions == []
    assert qyq.start_time == time(17, 0)  # 未被重排洗动
    assert bmy.start_time == time(9, 0)


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


# ---------- 2026-11-08 唐宴案三拍：宴秀占场 / 认领避宴日 / 就近留场 ----------

_QFJ = (108.9743, 34.2127)  # 大唐芙蓉园簇（御宴宫/《梦回大唐》同址锚）
_MTY = (108.9660, 34.2129)  # 曼蒂广场（长安十二时辰·唐宴）
_TLG = (108.9701, 34.3217)  # 唐乐宫（城北四海唐人街，距曲江簇 ~12km）


def _banquet(
    item_id,
    name,
    day,
    lon,
    lat,
    *,
    poi_id=None,
    dur=120,
    hours="午宴12:30场；晚宴18:30场（预订制）",
):
    return VisitItem(
        item_id=item_id,
        name=name,
        category="food",
        city="西安",
        day=day,
        duration_minutes=dur,
        location=GeoPoint(lon=lon, lat=lat),
        opening_hours=hours,
        poi_id=poi_id or f"curated:西安:{name}",
    )


def test_banquet_show_occupies_day_second_show_moves_off():
    # ⑪宴秀占场（沪→西→沪案 D2 实录）：御宴宫(宴)+唐宴(宴)+唐乐宫(演)
    # 三叠一天——终闸把宴秀计入当日演出位：宴秀留场（御宴宫 0km 贴簇
    # 首留），唐乐宫挪去无演出日，披露点名「宴秀」；唐宴按五拍「宴类
    # 簇跟随」取消（D1 回民街/D3 城墙都 >5km 无簇伴，不孤放别日）。
    dyt = _placed("v-dyt", "大雁塔", 2, *_QFJ, 90, start=10, category="attraction")
    yys = _banquet("v-yys", "御宴宫", 2, *_QFJ)
    tang = _banquet("v-tang", "长安十二时辰·唐宴", 2, *_MTY)
    tlg = _placed("v-tlg", "唐乐宫《大唐女皇》", 2, *_TLG, 80, start=19, show=True)
    plan = ItineraryPlan(
        itinerary_id="it-banquet",
        cities=["西安"],
        days=[
            DayPlan(
                day=1,
                base_city="西安",
                items=[_placed("v-hms", "回民街", 1, 108.94, 34.26, 90, start=9)],
            ),
            DayPlan(day=2, base_city="西安", items=[dyt, yys, tang, tlg]),
            DayPlan(
                day=3,
                base_city="西安",
                items=[
                    _placed(
                        "v-cq",
                        "城墙",
                        3,
                        108.9405,
                        34.2569,
                        120,
                        start=9,
                        category="attraction",
                    )
                ],
            ),
        ],
    )
    _enforce_show_per_day(plan)
    day_of = {
        i.name: i.day for d in plan.days for i in d.items if isinstance(i, VisitItem)
    }
    assert day_of["御宴宫"] == 2  # 宴秀留场（0km 贴簇）
    assert day_of["唐乐宫《大唐女皇》"] != 2  # 宴日演出让位
    # ⑮宴类簇跟随（2026-11-08 五拍「毕竟只是 FOOD」）：唐宴被挤出 D2、
    # 目标日均无 ≤5km 簇伴 → 不孤放别日、取消+披露
    assert "长安十二时辰·唐宴" not in day_of
    assert any("唐宴" in str(a) and "不孤放" in str(a) for a in plan.assumptions)
    # 宴日不再叠任何演出/第二宴秀
    for d in plan.days:
        occupied = [
            i
            for i in d.items
            if isinstance(i, VisitItem)
            and (_is_show_item(i) or _is_show_banquet_item(i))
        ]
        assert len(occupied) <= 1, "同日多场演出/宴秀：%r" % [i.name for i in occupied]
    assert any("宴秀" in str(a) and "唐乐宫" in str(a) for a in plan.assumptions)


def test_claim_never_targets_banquet_day():
    # ⑫认领避宴日：《梦回大唐》在 D3 无 ≤5km 伴、D2 芙蓉园 0km 有伴，
    # 但 D2 已是宴日（御宴宫占场）→ 不认领，留 D3 不动、零披露。
    dyt = _placed("v-dyt", "大唐芙蓉园", 2, *_QFJ, 120, start=9, category="attraction")
    yys = _banquet("v-yys", "御宴宫", 2, *_QFJ)
    wall = _placed(
        "v-cq", "城墙·碑林", 3, 108.9405, 34.2569, 150, start=9, category="attraction"
    )
    mhd = _placed("v-mhd", "《梦回大唐》", 3, *_QFJ, 80, start=19, show=True)
    plan = ItineraryPlan(
        itinerary_id="it-claim",
        cities=["西安"],
        days=[
            DayPlan(day=1, base_city="西安", items=[]),
            DayPlan(day=2, base_city="西安", items=[dyt, yys]),
            DayPlan(day=3, base_city="西安", items=[wall, mhd]),
        ],
    )
    _enforce_show_per_day(plan)
    mhd_it = next(
        i
        for d in plan.days
        for i in d.items
        if getattr(i, "name", "") == "《梦回大唐》"
    )
    assert mhd_it.day == 3  # 宴日不是认领目标
    assert plan.assumptions == []  # 零副作用
    assert yys.day == 2 and mhd_it.start_time == time(19, 0)


def test_nearest_show_kept_on_contested_day():
    # ⑬就近留场（「要排 SHOW 也应该找最近的」）：D2 两场演出竞争——
    # 《梦回大唐》同址 0km、唐乐宫 12km，且唐乐宫在册序在前（旧口径
    # 会留错的那个）：留近者，远者挪去 D1。
    dyt = _placed("v-dyt", "大雁塔", 2, *_QFJ, 90, start=10, category="attraction")
    tlg = _placed("v-tlg", "唐乐宫《大唐女皇》", 2, *_TLG, 80, start=19, show=True)
    mhd = _placed("v-mhd", "《梦回大唐》", 2, *_QFJ, 80, show=True)
    plan = ItineraryPlan(
        itinerary_id="it-near",
        cities=["西安"],
        days=[
            DayPlan(day=1, base_city="西安", items=[]),
            DayPlan(day=2, base_city="西安", items=[dyt, tlg, mhd]),
        ],
    )
    _enforce_show_per_day(plan)
    day_of = {
        i.name: i.day for d in plan.days for i in d.items if isinstance(i, VisitItem)
    }
    assert day_of["《梦回大唐》"] == 2  # 就近者留场
    assert day_of["唐乐宫《大唐女皇》"] == 1  # 远者让位挪日


def test_plain_curated_restaurant_does_not_occupy_show_slot():
    # ⑪防误伤：curated 普通餐厅（失重餐厅类，名/时段无宴秀语素）不占
    # 演出位——同日演出照常，零动作零披露。
    spc = _banquet("v-spc", "失重餐厅", 1, 108.94, 34.26, hours="10:00-22:00")
    mhd = _placed("v-mhd", "《梦回大唐》", 1, *_QFJ, 80, start=19, show=True)
    dyt = _placed("v-dyt", "大雁塔", 1, *_QFJ, 90, start=9, category="attraction")
    plan = ItineraryPlan(
        itinerary_id="it-plain",
        cities=["西安"],
        days=[
            DayPlan(day=1, base_city="西安", items=[dyt, spc, mhd]),
            DayPlan(day=2, base_city="西安", items=[]),
        ],
    )
    _enforce_show_per_day(plan)
    assert plan.assumptions == []
    assert spc.day == 1 and mhd.day == 1  # 普通餐不触发清算


def test_squeeze_swap_rescues_anchored_show():
    # ⑭挤兑救援（四拍「要排 SHOW 也应该找最近的」）：D3《梦回大唐》
    # 场次 12:00/12:30 全撞城墙 9:00-13:00 固定窗（±30+打车 pad）→挪位后
    # 仍无时刻待删，但 0km 贴 D2 大雁塔（强锚）；D1 唐乐宫在席但最近锚仅
    # 7.4km 回民街（弱锚）→ 换位：强锚顶 D1、弱锚去 D3 承接；驼铃（无日
    # 可挪）披露删除。
    hms = _placed("v-hms", "回民街", 1, 108.94, 34.26, 120, start=9, category="sight")
    tlg = _placed("v-tlg", "唐乐宫《大唐女皇》", 1, *_TLG, 80, start=19, show=True)
    dyt = _placed("v-dyt", "大雁塔", 2, *_QFJ, 120, start=9, category="sight")
    yys = _banquet("v-yys", "御宴宫", 2, *_QFJ)
    wall = _placed(
        "v-cq", "城墙·碑林", 3, 108.9405, 34.2569, 240, start=9, category="sight"
    )
    mhd = VisitItem(
        item_id="v-mhd",
        name="《梦回大唐》",
        category="entertainment",
        best_visit_time="show",
        city="西安",
        day=3,
        duration_minutes=80,
        location=GeoPoint(lon=_QFJ[0], lat=_QFJ[1]),
        opening_hours="多场（约12:00/12:30）",
    )
    tuoling = _placed("v-tlq", "《驼铃传奇》", 3, 109.01, 34.45, 80, show=True)
    plan = ItineraryPlan(
        itinerary_id="it-squeeze",
        cities=["西安"],
        days=[
            DayPlan(day=1, base_city="西安", items=[hms, tlg]),
            DayPlan(day=2, base_city="西安", items=[dyt, yys]),
            DayPlan(day=3, base_city="西安", items=[wall, mhd, tuoling]),
        ],
    )
    _enforce_show_per_day(plan)
    day_of = {
        i.name: i.day for d in plan.days for i in d.items if isinstance(i, VisitItem)
    }
    assert day_of["《梦回大唐》"] == 1  # 强锚顶上 D1 并获得时刻
    assert day_of["唐乐宫《大唐女皇》"] == 3  # 弱锚让位承接
    mhd_it = next(
        i
        for d in plan.days
        for i in d.items
        if isinstance(i, VisitItem) and i.name == "《梦回大唐》"
    )
    assert mhd_it.start_time is not None
    assert yys.day == 2  # 宴秀不受挤兑影响
    assert any("换位" in str(a) for a in plan.assumptions)
    assert any("驼铃传奇" in str(a) and "未排" in str(a) for a in plan.assumptions)
    for d in plan.days:
        occupied = [
            i
            for i in d.items
            if isinstance(i, VisitItem)
            and (_is_show_item(i) or _is_show_banquet_item(i))
        ]
        assert len(occupied) <= 1, "同日多场演出/宴秀：%r" % [i.name for i in occupied]


# ---------- 2026-11-08 雁塔案五拍：宴类簇跟随 / 最弱锚牺牲兜底 ----------


def test_banquet_moves_only_to_cluster_mate_day():
    # ⑮宴类簇跟随（五拍）：唐宴被挤出 D2 后，目标日 D3 有 ≤5km 簇伴
    # （曼蒂广场旁的白天点）→ 整簇合法挪日、照常挪不取消。
    dyt = _placed("v-dyt", "大雁塔", 2, *_QFJ, 90, start=10, category="attraction")
    yys = _banquet("v-yys", "御宴宫", 2, *_QFJ)
    tang = _banquet("v-tang", "长安十二时辰·唐宴", 2, *_MTY)
    mate = _placed(
        "v-mtds",
        "曼蒂广场白天点",
        3,
        108.9680,
        34.2130,
        60,
        start=14,
        category="attraction",
    )
    plan = ItineraryPlan(
        itinerary_id="it-banquet-mate",
        cities=["西安"],
        days=[
            DayPlan(day=1, base_city="西安", items=[]),
            DayPlan(day=2, base_city="西安", items=[dyt, yys, tang]),
            DayPlan(day=3, base_city="西安", items=[mate]),
        ],
    )
    _enforce_show_per_day(plan)
    day_of = {
        i.name: i.day for d in plan.days for i in d.items if isinstance(i, VisitItem)
    }
    assert day_of["御宴宫"] == 2
    assert day_of["长安十二时辰·唐宴"] == 3  # 目标日有簇伴→照常挪
    assert day_of["曼蒂广场白天点"] == 3
    for d in plan.days:
        occupied = [
            i
            for i in d.items
            if isinstance(i, VisitItem)
            and (_is_show_item(i) or _is_show_banquet_item(i))
        ]
        assert len(occupied) <= 1, "同日多场演出/宴秀：%r" % [i.name for i in occupied]


def test_no_free_day_sacrifices_weakest_anchored_show():
    # ⑯最弱锚牺牲兜底（雁塔案回归锚）：全城无空演出日时不再直接删本卡
    # ——D1 孤演《驼铃传奇》（~22km 无簇伴）被删腾位，贴簇强锚的
    # 《梦回大唐》（D2 0km 贴大雁塔）改落 D1；钉住宴御宴宫留场 D2。
    hms = _placed("v-hms", "回民街", 1, 108.94, 34.26, 90, start=9)
    tlq = _placed("v-tlq", "《驼铃传奇》", 1, 109.01, 34.45, 80, start=19, show=True)
    dyt = _placed("v-dyt", "大雁塔", 2, *_QFJ, 120, start=9, category="attraction")
    yys = _banquet("v-yys", "御宴宫", 2, *_QFJ)
    yys.pinned = True
    mhd = _placed("v-mhd", "《梦回大唐》", 2, *_QFJ, 80, show=True)
    plan = ItineraryPlan(
        itinerary_id="it-sacrifice",
        cities=["西安"],
        days=[
            DayPlan(day=1, base_city="西安", items=[hms, tlq]),
            DayPlan(day=2, base_city="西安", items=[dyt, yys, mhd]),
        ],
    )
    _enforce_show_per_day(plan)
    day_of = {
        i.name: i.day for d in plan.days for i in d.items if isinstance(i, VisitItem)
    }
    assert day_of["御宴宫"] == 2  # 钉住宴留场
    assert day_of["《梦回大唐》"] == 1  # 贴簇强锚顶掉孤演的日子
    assert "《驼铃传奇》" not in day_of  # 最弱锚（距当日簇最远无伴）被删
    assert any("驼铃传奇" in str(a) and "让位" in str(a) for a in plan.assumptions)
    for d in plan.days:
        occupied = [
            i
            for i in d.items
            if isinstance(i, VisitItem)
            and (_is_show_item(i) or _is_show_banquet_item(i))
        ]
        assert len(occupied) <= 1, "同日多场演出/宴秀：%r" % [i.name for i in occupied]
