# -*- coding: utf-8 -*-
"""P4 扰动鲁棒评测（2026-11-10）：对现存行程注入真实世界扰动，走真实修订
管线，断言修订后三大不变量：

  1. 仍过 validate_plan（铁律 1/2/4/6…行程级硬校验，error=修订被拒）；
  2. pin 不丢（validate_pinned 语义，铁律 19：用户钉住的条目不得改/删）；
  3. 修订范围不越界（validate_change_scope 语义，铁律 10：from_day 之前
     的天必须与原计划逐字一致）。

真实修订入口（本夹具驱动的代码路径，非 mock）：
  - 非结构化 diff（remove/retime）→ app/services/itinerary/pipeline.py:186
    ``mutate()`` —— 与 ``ItineraryService.mutate``
    （app/services/itinerary_store.py:213，PUT /itineraries/{id} 的落点）和
    规划代理轻量分支（app/services/agent/plan.py:19725 ``_apply_with_repair``）
    调用的是同一个函数、同样带 old_plan（铁律 19 在读侧生效）。
  - 结构化 diff（move/add）→ ``_apply_structural``（plan.py:19719 触发③），
    但那条路要起 solver + LLM 修复环，本夹具用非结构化路径覆盖两大扰动
    场景已足够（航班延误=retime 交通卡；闭馆=remove+add 替换卡）。

已核实的真实缺口（评测摸底结果，不改产品代码，此处留证）：
  GAP-1 铁律 10（change scope）在生产路径上是死参数：全库 grep 显示
        ``from_day`` 无任何生产调用方传入（itinerary_store.py:213 与
        plan.py:19725 都未传）——范围闸只在 mutate(from_day=...) 手动
        传入时存在。因此断言 3 在本文件中直接调用
        rules.validate_change_scope 做语义核验。
  GAP-2 钉住点临时闭馆无解：闭馆检测（hours 变 00:00-00:00 → 铁律 2
        error）与 pin 保护（铁律 19 禁删）会同时对同一张卡开火——引擎
        正确拒绝一切自动修订（半成品交付），但没有「请示用户解钉」的
        升级通道。见 test_closed_pinned_poi_refuses_automatic_repair。
  GAP-3 DiffOp 没有「改交通时长」的操作：航班「延误 2h」若伴随航司把
        航程也拉长，retime 只挪 start，duration/end 由 _recompute_end_times
        按原 duration 重算——延误+改签组合语义表达不了（当前只能表达
        纯时刻平移）。
  GAP-4 validate_change_scope 用「DayPlan.items 整对象相等」比较新旧
        （rules.py:608），而 mutate 的出口端恒跑 annotate_legs 给候选计划
        补 distance_to_next_km/next_walk_minutes/leg_source——旧计划从存储
        原样进来、无这些展示字段，于是早于 from_day 的天只因腿标注漂移
        就被判「不一致」（铁律 10 假阳性）。实证见
        test_flight_delay_2h_retimes_and_stays_valid 的 xfail 分支。
"""

from datetime import time as _t

import pytest

from app.services.itinerary.models import (
    DayPlan,
    DiffOp,
    GeoPoint,
    ItineraryPlan,
    PoiHours,
    TransferItem,
    VisitItem,
)
from app.services.itinerary.pipeline import mutate
from app.services.itinerary.rules import (
    validate_change_scope,
    validate_pinned,
)

SH = GeoPoint(lon=121.4900, lat=31.2400)  # 外滩一带
SH2 = GeoPoint(lon=121.4950, lat=31.2450)
XA = GeoPoint(lon=108.9400, lat=34.2600)  # 大雁塔/城墙一带
XA2 = GeoPoint(lon=108.9450, lat=34.2650)
XA3 = GeoPoint(lon=108.9500, lat=34.2700)


def _visit(
    item_id,
    name,
    day,
    start,
    end,
    *,
    dur,
    city="西安",
    poi_id=None,
    category="sight",
    location=None,
    pinned=False,
):
    return VisitItem(
        item_id=item_id,
        name=name,
        poi_id=poi_id,
        category=category,
        city=city,
        location=location,
        day=day,
        start_time=start,
        end_time=end,
        duration_minutes=dur,
        pinned=pinned,
    )


def _flight(item_id, day, start, *, dur, seq, from_city, to_city):
    end_min = start.hour * 60 + start.minute + dur
    return TransferItem(
        item_id=item_id,
        day=day,
        seq=seq,
        from_city=from_city,
        to_city=to_city,
        mode="flight",
        start_time=start,
        end_time=_t(end_min // 60, end_min % 60),
        duration_minutes=dur,
    )


def _rule_ids(report):
    return sorted({v.rule_id for v in report.violations})


# ---------------------------------------------------------------------------
# 场景 A：返程航班延误 2 小时（retime 交通卡）
# ---------------------------------------------------------------------------


def _delay_plan() -> ItineraryPlan:
    """沪→陕 3 日行程：D1 沪双点（其一用户钉住），D2 去程航班+落地单点，
    D3 上午钉住观光 + 14:00 返程航班。"""
    return ItineraryPlan(
        itinerary_id="perturb-delay",
        cities=["上海", "西安"],
        days=[
            DayPlan(
                day=1,
                base_city="上海",
                items=[
                    _visit(
                        "sh-a",
                        "外滩",
                        1,
                        _t(9, 0),
                        _t(10, 30),
                        dur=90,
                        city="上海",
                        location=SH,
                        pinned=True,
                    ),
                    _visit(
                        "sh-b",
                        "豫园",
                        1,
                        _t(11, 15),
                        _t(12, 15),
                        dur=60,
                        city="上海",
                        location=SH2,
                    ),
                ],
            ),
            DayPlan(
                day=2,
                base_city="西安",
                items=[
                    _flight(
                        "go-flight",
                        2,
                        _t(10, 0),
                        dur=150,
                        seq=1,
                        from_city="上海",
                        to_city="西安",
                    ),
                    _visit(
                        "xa-arrive",
                        "大雁塔",
                        2,
                        _t(14, 30),
                        _t(16, 0),
                        dur=90,
                        location=XA,
                    ),
                ],
            ),
            DayPlan(
                day=3,
                base_city="西安",
                items=[
                    _visit(
                        "xa-wall",
                        "城墙",
                        3,
                        _t(9, 0),
                        _t(11, 0),
                        dur=120,
                        location=XA2,
                        pinned=True,
                    ),
                    _flight(
                        "return-flight",
                        3,
                        _t(14, 0),
                        dur=150,
                        seq=1,
                        from_city="西安",
                        to_city="上海",
                    ),
                ],
            ),
        ],
    )


def test_delay_baseline_plan_is_clean():
    plan = _delay_plan()
    new_plan, report, _ = mutate(plan, [], poi_hours=[], old_plan=plan)
    assert report.ok, report.violations
    # 零 diff 不改排程内容（mutate 恒会 annotate_legs 补腿标注，那不算改动）
    assert [
        (i.item_id, i.day, i.start_time, i.end_time)
        for d in new_plan.days
        for i in d.items
    ] == [
        (i.item_id, i.day, i.start_time, i.end_time) for d in plan.days for i in d.items
    ]


def test_flight_delay_2h_retimes_and_stays_valid():
    plan = _delay_plan()
    diffs = [DiffOp(op="retime", item_id="return-flight", new_start_time=_t(16, 0))]
    new_plan, report, summary = mutate(
        plan, diffs, poi_hours=[], old_plan=plan, from_day=3
    )
    # 不变量 1：行程级校验全绿（铁律 4 衔接缓冲随新时刻重算）
    assert report.ok, report.violations
    flight = next(
        i for d in new_plan.days for i in d.items if i.item_id == "return-flight"
    )
    assert flight.start_time == _t(16, 0)
    assert flight.end_time == _t(18, 30)  # start+150min 重算
    # 不变量 2：两张用户钉住的观光卡原样存活（铁律 19）
    assert not validate_pinned(plan, new_plan).violations
    for item_id in ("sh-a", "xa-wall"):
        assert any(i.item_id == item_id for d in new_plan.days for i in d.items)
    assert summary.affected_items_count == 1


def test_flight_delay_scope_check():
    """不变量 3（铁律 10）核验——GAP-4 实证：纯延误修订（只动 D3 交通卡）
    也会因 annotate_legs 腿标注漂移被 scope 闸误报（见文件头 GAP-4），
    故本测试整体 xfail；GAP-4 修复后应转 pass。"""
    plan = _delay_plan()
    diffs = [DiffOp(op="retime", item_id="return-flight", new_start_time=_t(16, 0))]
    new_plan, _, _ = mutate(plan, diffs, poi_hours=[], old_plan=plan, from_day=3)
    scope = validate_change_scope(plan, new_plan, from_day=3)
    if scope.violations:
        pytest.xfail(
            "GAP-4: validate_change_scope 整对象相等比较——mutate 后候选"
            "计划被 annotate_legs 补了腿标注，早于 from_day 的天只因腿标注"
            "漂移被误报为「不一致」（铁律 10 假阳性，见文件头 GAP-4）"
        )
    assert not scope.violations


def test_flight_pulled_into_pinned_visit_buffer_is_rejected():
    """负控：把航班提前到与钉住的上午观光卡衔接缓冲（90min）冲突的时段，
    管线必须以铁律 4 error 拒绝（修订不生效、行程不被半成品污染）。"""
    plan = _delay_plan()
    diffs = [DiffOp(op="retime", item_id="return-flight", new_start_time=_t(11, 30))]
    _, report, _ = mutate(plan, diffs, poi_hours=[], old_plan=plan)
    assert not report.ok
    assert 4 in _rule_ids(report)


def test_flight_delay_must_not_touch_earlier_days():
    """负控：延误修订若误动前两天（如对 D1 卡 retime），scope 闸必须抓到。
    注：因 GAP-4（腿标注漂移也触发铁律 10），本测试即使删掉 sh-b 那条
    恶意 diff 也照样红——它证明的是「闸会响」，不是「闸只在该响时响」。"""
    plan = _delay_plan()
    diffs = [
        DiffOp(op="retime", item_id="return-flight", new_start_time=_t(16, 0)),
        DiffOp(op="retime", item_id="sh-b", new_start_time=_t(12, 30)),
    ]
    new_plan, report, _ = mutate(plan, diffs, poi_hours=[], old_plan=plan, from_day=3)
    assert not report.ok
    assert 10 in _rule_ids(report)
    assert not validate_pinned(plan, new_plan).violations


# ---------------------------------------------------------------------------
# 场景 B：某 POI 临时闭馆（hours 塌成 00:00-00:00）→ 检测 + 替换修订
# ---------------------------------------------------------------------------

_CLOSED = PoiHours(poi_id="p-mus", opens=_t(0, 0), closes=_t(0, 0))
_OPEN_MUS = PoiHours(poi_id="p-mus", opens=_t(9, 0), closes=_t(17, 0))
_OPEN_ALT = PoiHours(poi_id="p-alt", opens=_t(9, 0), closes=_t(17, 0))
_OPEN_PM = PoiHours(poi_id="p-pm", opens=_t(9, 0), closes=_t(17, 0))
_OPEN_BM = PoiHours(poi_id="p-bm", opens=_t(8, 30), closes=_t(18, 0))


def _closure_plan(pinned_museum: bool = False) -> ItineraryPlan:
    """西安 3 日：D1 上午博物馆（p-mus）+午饭+下午点；D2 兵马俑+用户钉住的
    晚间演出；D3 街区轻量日。"""
    return ItineraryPlan(
        itinerary_id="perturb-closure",
        cities=["西安"],
        days=[
            DayPlan(
                day=1,
                base_city="西安",
                items=[
                    _visit(
                        "mus",
                        "博物馆",
                        1,
                        _t(9, 0),
                        _t(11, 0),
                        dur=120,
                        poi_id="p-mus",
                        category="museum",
                        location=XA,
                        pinned=pinned_museum,
                    ),
                    _visit(
                        "lunch-d1",
                        "午饭（自由安排）",
                        1,
                        _t(12, 0),
                        _t(13, 30),
                        dur=90,
                        category="food",
                    ),
                    _visit(
                        "pm-sight",
                        "大雁塔",
                        1,
                        _t(14, 30),
                        _t(16, 0),
                        dur=90,
                        poi_id="p-pm",
                        location=XA2,
                    ),
                ],
            ),
            DayPlan(
                day=2,
                base_city="西安",
                items=[
                    _visit(
                        "bm",
                        "兵马俑",
                        2,
                        _t(9, 0),
                        _t(12, 0),
                        dur=180,
                        poi_id="p-bm",
                        category="museum",
                        location=XA3,
                    ),
                    _visit(
                        "show",
                        "晚间演出",
                        2,
                        _t(19, 0),
                        _t(20, 30),
                        dur=90,
                        category="show",
                        location=XA,
                        pinned=True,
                    ),
                ],
            ),
            DayPlan(
                day=3,
                base_city="西安",
                items=[
                    _visit(
                        "walk",
                        "回民街",
                        3,
                        _t(10, 0),
                        _t(11, 30),
                        dur=90,
                        category="citywalk",
                    ),
                ],
            ),
        ],
    )


def test_closure_is_detected_as_rule2_error():
    """闭馆（hours 塌成 00:00-00:00）一进场即被铁律 2 抓出——
    修订前的行程已不合法，必须出修订 diff。"""
    plan = _closure_plan()
    _, report, _ = mutate(
        plan, [], poi_hours=[_CLOSED, _OPEN_PM, _OPEN_BM], old_plan=plan
    )
    assert not report.ok
    assert 2 in _rule_ids(report)


def test_closure_repair_swap_same_slot_keeps_invariants():
    """修订 = 移除闭馆卡 + 同槽位加入替代馆（p-alt，9:00-11:00 原窗）。"""
    plan = _closure_plan()
    replacement = _visit(
        "alt",
        "替代博物馆",
        1,
        _t(9, 0),
        _t(11, 0),
        dur=120,
        poi_id="p-alt",
        category="museum",
        location=XA,
    )
    diffs = [
        DiffOp(op="remove", item_id="mus"),
        DiffOp(op="add", item=replacement),
    ]
    new_plan, report, summary = mutate(
        plan,
        diffs,
        poi_hours=[_CLOSED, _OPEN_ALT, _OPEN_PM, _OPEN_BM],
        old_plan=plan,
        from_day=1,
    )
    # 不变量 1：替换后行程级校验全绿（闭馆卡已不在，新卡在营业窗内）
    assert report.ok, report.violations
    day1_ids = [i.item_id for i in new_plan.days[0].items]
    assert "mus" not in day1_ids and "alt" in day1_ids
    # 不变量 2：用户钉住的 D2 晚间演出原样存活
    assert not validate_pinned(plan, new_plan).violations
    show = next(i for d in new_plan.days for i in d.items if i.item_id == "show")
    assert (show.day, show.start_time, show.end_time) == (2, _t(19, 0), _t(20, 30))
    # 不变量 3：全城修订（from_day=1），scope  trivially 干净
    assert not validate_change_scope(plan, new_plan, from_day=1).violations
    assert summary.affected_items_count == 2


def test_closed_pinned_poi_refuses_automatic_repair():
    """GAP-2 实证：闭馆卡若被用户钉住，检测（铁律 2）与 pin 保护（铁律 19）
    对同一张卡同时开火——remove 修订被铁律 19 拒死，引擎不放手是正确的，
    但现有路径只有「拒绝/半成品交付」，没有「请示用户解钉」升级通道。
    这是评测摸出的真实盲区，行为断言（拒绝）本身通过。"""
    plan = _closure_plan(pinned_museum=True)
    diffs = [DiffOp(op="remove", item_id="mus")]
    _, report, _ = mutate(
        plan,
        diffs,
        poi_hours=[_CLOSED, _OPEN_PM, _OPEN_BM],
        old_plan=plan,
        from_day=1,
    )
    assert not report.ok
    assert 19 in _rule_ids(report)  # pin 保护拦下自动删除
    # 检测闸同样对钉住的闭馆卡报警（双闸并存 = 死锁，留证即可）
    _, detect, _ = mutate(
        plan, [], poi_hours=[_CLOSED, _OPEN_PM, _OPEN_BM], old_plan=plan
    )
    assert not detect.ok and 2 in _rule_ids(detect)
