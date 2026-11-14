"""街区 + 同址宴秀硬绑同日（2026-11-13 用户拍板）。

用户原话：「in new test, 长安十二时辰 街区和唐宴被分开两天，FIX. 街区和
餐饮是一族，可以删除一项，但是不能分开。」以及「长安十二时辰 街 240
分钟实际上是包含了晚宴唐宴的。。所以是硬绑定」。

两道闸：
1. `_fallback_sequence_times` 的撞窗判定反向同址豁免——240min 街区落位时，
   同在 18:30 的唐宴若整段嵌进候选窗就不算占窗（街区时间包含晚宴），街区
   不再被宴卡判死挪去别天。
2. `_bind_block_family` 交付前对账——任何结构相位把两者拆到两天都合回，
   宴卡嵌进街区窗；宿主窗容不下则删宴卡留痕，绝不拆天。
"""

from datetime import time

from app.services.agent.plan import _bind_block_family, _fallback_sequence_times
from app.services.itinerary.models import (
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    VisitItem,
)

# 西安·曼蒂广场（长安十二时辰街区与唐宴同址 ≈0.1km）
_BLOCK = GeoPoint(lon=108.966004, lat=34.21198)
_TANG = GeoPoint(lon=108.966054, lat=34.212854)
_DYT = GeoPoint(lon=108.9640, lat=34.2180)
_SXL = GeoPoint(lon=108.9400, lat=34.2300)


def _visit(
    name,
    category,
    xy,
    *,
    day=1,
    dur=60,
    start=None,
    end=None,
    hours=None,
    item_id=None,
):
    return VisitItem(
        item_id=item_id or f"v-{name}",
        name=name,
        poi_id=f"curated:西安:{name}",
        category=category,
        city="西安",
        location=xy,
        day=day,
        duration_minutes=dur,
        start_time=start,
        end_time=end,
        opening_hours=hours,
    )


def _block(day=1, start=None, end=None):
    return _visit(
        "长安十二时辰主题街区",
        "citywalk",
        _BLOCK,
        day=day,
        dur=240,
        start=start,
        end=end,
        hours="全天滚动演艺（10:00-22:00）",
    )


def _tang(day=1, start=None, end=None):
    return _visit(
        "长安十二时辰·唐宴",
        "food",
        _TANG,
        day=day,
        dur=60,
        start=start,
        end=end,
        hours="午宴12:30场；晚宴18:30场（预订制）",
    )


def _plan(days):
    return ItineraryPlan(itinerary_id="it-block-family", cities=["西安"], days=days)


def test_block_times_around_nested_banquet_instead_of_being_moved():
    """D2 已有 18:30 唐宴时，240min 街区仍能在同日落 17 点档（含晚宴）。"""
    block = _block()
    day = DayPlan(
        day=1,
        base_city="西安",
        items=[
            _visit(
                "大雁塔大唐芙蓉园景区",
                "attraction",
                _DYT,
                dur=180,
                start=time(9, 0),
                end=time(12, 0),
            ),
            _visit(
                "陕西历史博物馆",
                "museum",
                _SXL,
                dur=240,
                start=time(12, 35),
                end=time(16, 35),
            ),
            _tang(start=time(18, 30), end=time(19, 30)),
            block,
        ],
    )
    plan = _plan([day])
    _fallback_sequence_times(plan)

    assert block.start_time is not None, "街区不应被同址晚宴判死（应可落 17 点档）"
    assert block.end_time is not None
    dinner = next(i for i in day.items if i.name == "长安十二时辰·唐宴")
    assert dinner.start_time == time(18, 30)
    hs = block.start_time.hour * 60 + block.start_time.minute
    he = block.end_time.hour * 60 + block.end_time.minute
    ds = dinner.start_time.hour * 60 + dinner.start_time.minute
    de = dinner.end_time.hour * 60 + dinner.end_time.minute
    assert hs <= ds and de <= he, "晚宴应整段嵌进街区窗"


def test_split_days_are_reunited_and_dinner_nested():
    """新测实录形态：唐宴 D2 18:30、街区 D3 17:00-21:00 → 合回同一日。"""
    d2 = DayPlan(
        day=2,
        base_city="西安",
        items=[
            _visit("大雁塔", "attraction", _DYT, day=2, dur=180),
            _tang(day=2, start=time(18, 30), end=time(19, 30)),
        ],
    )
    d3 = DayPlan(
        day=3,
        base_city="西安",
        items=[_block(day=3, start=time(17, 0), end=time(21, 0))],
    )
    plan = _plan([d2, d3])

    notes = _bind_block_family(plan)

    block = next(
        i for d in plan.days for i in d.items if i.name == "长安十二时辰主题街区"
    )
    dinner = next(
        i for d in plan.days for i in d.items if i.name == "长安十二时辰·唐宴"
    )
    assert dinner.day == block.day == 3, "街区与同址晚宴不得拆天"
    assert not any(i.name == "长安十二时辰·唐宴" for i in d2.items)
    assert dinner.start_time == time(18, 30)
    assert dinner.end_time == time(19, 30)
    assert notes and any("一族" in str(n) for n in notes)


def test_short_host_window_keeps_proper_dinner_and_drops_block():
    """宿主窗装不下、但这顿在正晚餐档（18:30）：删街区卡留餐厅。

    2026-11-14 用户拍板「宿主窗实在容不下也可以删街区卡，取决于时间是否
    合适午餐晚餐」。
    """
    d2 = DayPlan(day=2, base_city="西安", items=[_tang(day=2, start=time(18, 30))])
    d3 = DayPlan(
        day=3,
        base_city="西安",
        items=[_block(day=3, start=time(17, 0), end=time(17, 40))],
    )
    plan = _plan([d2, d3])

    notes = _bind_block_family(plan)

    names = [i.name for d in plan.days for i in d.items if isinstance(i, VisitItem)]
    assert "长安十二时辰主题街区" not in names, "正餐档的这顿该留下，街区卡让位"
    assert any(u.name == "长安十二时辰主题街区" for u in plan.unplaced)
    dinner = next(
        i for d in plan.days for i in d.items if i.name == "长安十二时辰·唐宴"
    )
    assert dinner.start_time == time(18, 30)
    assert dinner.end_time == time(19, 30)
    assert notes and any("倾向删街卡" in str(n) for n in notes)


def test_short_window_with_odd_meal_time_drops_the_meal_card():
    """先看时间：这顿夹在下午茶档（15:20）不算午餐/晚餐 → 删餐卡留街区。"""
    odd = _visit(
        "同址小馆",
        "food",
        _TANG,
        day=2,
        start=time(15, 20),
        end=time(16, 20),
        hours="15:20场（下午茶）",
    )
    d2 = DayPlan(day=2, base_city="西安", items=[odd])
    d3 = DayPlan(
        day=3,
        base_city="西安",
        items=[_block(day=3, start=time(17, 0), end=time(17, 40))],
    )
    plan = _plan([d2, d3])

    notes = _bind_block_family(plan)

    names = [i.name for d in plan.days for i in d.items if isinstance(i, VisitItem)]
    assert "长安十二时辰主题街区" in names, "时间不合适时街区卡留下"
    assert "同址小馆" not in names
    assert any(u.name == "同址小馆" for u in plan.unplaced)
    assert notes and any("不可拆天" in str(n) for n in notes)


def test_untimed_meal_gets_default_dinner_slot_when_block_dropped():
    """无时刻的同址宴：删街区卡后按默认晚饭档落位（17:30），不留在灰卡。"""
    tang = _visit(
        "长安十二时辰·唐宴",
        "food",
        _TANG,
        day=2,
        dur=60,
        hours="午宴12:30场；晚宴18:30场（预订制）",
    )
    d2 = DayPlan(day=2, base_city="西安", items=[tang])
    d3 = DayPlan(
        day=3,
        base_city="西安",
        items=[_block(day=3, start=time(17, 0), end=time(17, 40))],
    )
    plan = _plan([d2, d3])

    _bind_block_family(plan)

    names = [i.name for d in plan.days for i in d.items if isinstance(i, VisitItem)]
    assert "长安十二时辰主题街区" not in names
    kept = next(i for d in plan.days for i in d.items if i.name == "长安十二时辰·唐宴")
    assert kept.start_time == time(18, 30), "有原时刻/场次就按正餐档落位"
    assert kept.end_time == time(19, 30)


def test_system_pinned_banquet_still_nests_into_block():
    """系统钉（pinned+soft_pin）不是用户权威：同日同址仍要嵌进街区窗。

    11-14 实录：唐宴被排程自己钉在 11:30 午卡（pinned=True, soft_pin=True），
    硬钉守卫把它跳过后，街区与晚宴同天却不嵌窗。
    """
    block = _block(day=2, start=time(17, 0), end=time(21, 0))
    tang = _tang(day=2, start=time(11, 30), end=time(12, 0))
    tang.pinned = True
    tang.soft_pin = True
    plan = _plan([DayPlan(day=2, base_city="西安", items=[block, tang])])

    notes = _bind_block_family(plan)

    assert tang.start_time == time(18, 30), "系统钉也该嵌回街区窗"
    assert tang.end_time == time(19, 30)
    assert notes and any("已嵌入" in str(n) for n in notes)


def test_user_pinned_banquet_is_not_moved_across_days():
    """用户手钉（soft_pin=False）跨天不搬：铁律 19 仍是最高权威。"""
    tang = _tang(day=2, start=time(18, 30))
    tang.pinned = True  # 用户 pin 端点：soft_pin 保持 False
    block = _block(day=3, start=time(17, 0), end=time(21, 0))
    plan = _plan([
        DayPlan(day=2, base_city="西安", items=[tang]),
        DayPlan(day=3, base_city="西安", items=[block]),
    ])

    _bind_block_family(plan)

    assert tang.day == 2, "用户钉住的卡不许被家族规则跨天搬走"


def test_pinned_block_wins_over_short_window_and_dinner_dropped():
    """街区卡被用户钉住时反过来：删餐厅留街区（铁律 19）。"""
    d2 = DayPlan(day=2, base_city="西安", items=[_tang(day=2, start=time(18, 30))])
    block = _block(day=3, start=time(17, 0), end=time(17, 40))
    block.pinned = True
    d3 = DayPlan(day=3, base_city="西安", items=[block])
    plan = _plan([d2, d3])

    notes = _bind_block_family(plan)

    names = [i.name for d in plan.days for i in d.items if isinstance(i, VisitItem)]
    assert "长安十二时辰主题街区" in names, "钉住的街区卡不删"
    assert "长安十二时辰·唐宴" not in names
    assert any(u.name == "长安十二时辰·唐宴" for u in plan.unplaced)
    assert notes and any("不可拆天" in str(n) for n in notes)


def test_far_food_is_not_bound():
    """>0.5km 的普通餐厅不成族：不搬、不嵌。"""
    far = GeoPoint(lon=108.99, lat=34.25)
    other = _visit(
        "钟楼旁的馆子",
        "food",
        far,
        day=2,
        start=time(18, 30),
        hours="午宴12:30场；晚宴18:30场（预订制）",
    )
    d2 = DayPlan(day=2, base_city="西安", items=[other])
    d3 = DayPlan(
        day=3,
        base_city="西安",
        items=[_block(day=3, start=time(17, 0), end=time(21, 0))],
    )
    plan = _plan([d2, d3])
    _bind_block_family(plan)
    assert any(i.name == "钟楼旁的馆子" for i in d2.items)
    assert not any(i.name == "钟楼旁的馆子" for i in d3.items)