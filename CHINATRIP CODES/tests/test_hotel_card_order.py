# -*- coding: utf-8 -*-
"""R13p（2026-11-21 用户拍板）：DAY2 酒店卡不应出现在天安门后——「酒店卡
如果出现应该是第一位的」。三修回归：

① _push_flag_successors 只推真正压住锚区间的卡（此前凡 s < 锚end+10 一律
   推，把合法排在锚**之前**的晨卡也推到锚后），且酒店卡（晨/夜）绝不推；
② _apply_flag_schedule 锚重定位后把被压在锚后的晨卡拉回锚前
   （结束 = 锚start−30，C-13 HOTEL_MORNING_MINUTES 打包窗口径）；
③ _plan_for_response 终态归位：晨卡恒最前、夜卡恒最后、其余卡按开始时刻
   稳定重排（修升旗缝尾 realign 只改时刻不动位次的乱序），旧坏快照里被
   推走的晨卡钳回首个非酒店卡之前。
"""

from datetime import time

from app.services.itinerary.models import DayPlan, ItineraryPlan, VisitItem


def _card(item_id, name, cat, start, end, **extra):
    if start is None:
        st = en = None
        dur = extra.pop("duration_minutes", None)
    else:
        st = time(start // 60, start % 60)
        en = time(end // 60, end % 60)
        dur = end - start
    return VisitItem(
        item_id=item_id,
        name=name,
        category=cat,
        city="北京",
        day=1,
        start_time=st,
        end_time=en,
        duration_minutes=dur,
        **extra,
    )


def _plan(*items, start_date=None):
    return ItineraryPlan(
        itinerary_id="it-r13p",
        cities=["北京"],
        start_date=start_date,
        days=[DayPlan(day=1, base_city="北京", items=list(items))],
    )


def _m(item):
    return item.start_time.hour * 60 + item.start_time.minute


# ---------- ① _push_flag_successors：锚前晨卡绝不被推 ----------


def test_push_spares_morning_card_before_anchor():
    """用户实锤形状：晨卡 06:41-07:11（C-13 保证晨卡结束 ≤ 当天首卡
    开始）、锚 07:11-08:41——晨卡不与锚区间重叠，绝不能被推到锚后
    （旧行为：s=06:41 < 锚end+10 一律推 → 晨卡 08:51 出现在天安门后）。"""
    from app.services.agent.plan import _push_flag_successors

    morning = _card(
        "hotel-morning-d2",
        "🏨 从酒店出发",
        "hotel",
        6 * 60 + 41,
        7 * 60 + 11,
        synthetic=True,
        soft_pin=True,
    )
    anchor = _card(
        "v1", "天安门广场", "attraction", 7 * 60 + 11, 8 * 60 + 41, pinned=True
    )
    tiantan = _card("v2", "天坛", "temple", 8 * 60 + 30, 10 * 60 + 53)
    plan = _plan(morning, anchor, tiantan)
    _push_flag_successors(plan.days[0], anchor)
    assert _m(morning) == 6 * 60 + 41  # 晨卡原地不动
    assert morning.end_time == time(7, 11)
    assert (
        _m(tiantan) == 8 * 60 + 51
    )  # R12-G 真重叠（天坛案）照旧推平：锚 08:41 + 10 地板


def test_push_never_moves_hotel_cards_even_if_overlapping():
    """晨卡与锚重叠（旧坏快照）时也不推——回拉是 _apply_flag_schedule 的
    职责；推平链对酒店卡一律豁免（「酒店卡应该是第一位的」）。夜卡同理。"""
    from app.services.agent.plan import _push_flag_successors

    morning = _card(
        "hotel-morning-d2",
        "🏨 从酒店出发",
        "hotel",
        8 * 60 + 30,
        9 * 60,
        synthetic=True,
        soft_pin=True,
    )
    anchor = _card(
        "v1", "天安门广场", "attraction", 7 * 60 + 10, 8 * 60 + 40, pinned=True
    )
    plan = _plan(anchor, morning)
    _push_flag_successors(plan.days[0], anchor)
    assert _m(morning) == 8 * 60 + 30


# ---------- ② _apply_flag_schedule：锚重定位后晨卡拉回锚前 ----------


def test_flag_realign_pulls_morning_before_anchor(monkeypatch):
    """引擎 A 形状（本次 :8000 复现）：solver 未钉旗时天安门 12:00 中午
    场、晨卡 08:50；缝尾打标 07:10 后晨卡被压在锚后——必须拉回锚前
    （结束 06:40 = 锚start−30，C-13 打包窗口径），锚后的真重叠照旧推平。"""
    import app.services.flag_schedule as fs
    from app.services.agent.plan import _apply_flag_schedule

    monkeypatch.setattr(
        fs, "get_flag_time", lambda d, k: time(7, 10) if k == "morning" else None
    )
    morning = _card(
        "hotel-morning-d1",
        "🏨 从酒店出发",
        "hotel",
        8 * 60 + 50,
        9 * 60 + 20,
        synthetic=True,
        soft_pin=True,
    )
    anchor = _card("v1", "天安门广场", "attraction", 12 * 60, 13 * 60 + 30)
    tiantan = _card("v2", "天坛", "temple", 8 * 60 + 30, 10 * 60 + 53)
    plan = _plan(morning, anchor, tiantan, start_date="2026-11-25")
    _apply_flag_schedule(plan)
    assert anchor.fixed_sessions == [time(7, 10)]
    assert _m(anchor) == 7 * 60 + 10
    assert morning.end_time == time(6, 40)
    assert morning.start_time == time(6, 10)  # 结束 −30 时长
    assert _m(tiantan) == 8 * 60 + 50  # 07:10 realign 后天坛 08:30 重叠 → 推平


def test_flag_realign_pulls_stale_pushed_morning():
    """旧坏快照自愈：晨卡已被推到锚后（08:51-09:21），再次过
    _apply_flag_schedule（fixed 在册 realign 分支，消息回合幂等重跑）时
    拉回锚前。"""
    from app.services.agent.plan import _apply_flag_schedule

    morning = _card(
        "hotel-morning-d2",
        "🏨 从酒店出发",
        "hotel",
        8 * 60 + 51,
        9 * 60 + 21,
        synthetic=True,
        soft_pin=True,
    )
    anchor = _card(
        "v1",
        "天安门广场",
        "attraction",
        7 * 60 + 10,
        8 * 60 + 40,
        fixed_sessions=[time(7, 10)],
        pinned=True,
    )
    plan = _plan(morning, anchor)
    _apply_flag_schedule(plan)
    assert _m(anchor) == 7 * 60 + 10  # realign 幂等
    assert morning.end_time == time(6, 40)
    assert morning.start_time == time(6, 10)


# ---------- ③ _plan_for_response 终态归位 ----------


def test_response_reorders_after_flag_realign():
    """升旗 realign 后的乱序快照（本次 :8000 复现形状）：天安门 07:10 显示
    在 day 中部（前面还是 09:30 的八达岭）→ 响应终态：晨卡最前、天安门
    紧随、其余按开始时刻稳定重排、夜卡最后；晨卡钳回首个非酒店卡之前。
    非变异：会话本体与持久快照不动。"""
    from app.api.plan import _hotel_cards_front_back

    morning = _card(
        "hotel-morning-d1",
        "🏨 从酒店出发",
        "hotel",
        8 * 60 + 50,
        9 * 60 + 20,
        synthetic=True,
        soft_pin=True,
    )
    badaling = _card("v5", "八达岭长城", "historic", 9 * 60 + 30, 12 * 60 + 30)
    lunch = _card("meal-lunch-1", "午餐", "food", 11 * 60 + 30, 12 * 60 + 30)
    anchor = _card("v1", "天安门广场", "attraction", 7 * 60 + 10, 8 * 60 + 40)
    ret = _card(
        "access-return-v1",
        "🚌 回城",
        "transfer",
        12 * 60 + 45,
        13 * 60 + 55,
        synthetic=True,
    )
    tiantan = _card("v6", "天坛", "temple", 16 * 60, 18 * 60 + 30)
    dinner = _card("meal-dinner-1", "晚饭", "food", 17 * 60, 18 * 60 + 30)
    night = _card(
        "hotel-night-d1",
        "🏨 回酒店·夜间休息",
        "hotel",
        21 * 60,
        21 * 60 + 30,
        synthetic=True,
        soft_pin=True,
    )
    plan = _plan(morning, badaling, lunch, anchor, ret, tiantan, dinner, night)
    out = _hotel_cards_front_back(plan)
    ids = [i.item_id for i in out.days[0].items]
    assert ids[0] == "hotel-morning-d1"
    assert ids[-1] == "hotel-night-d1"
    assert ids[1] == "v1"  # 天安门 07:10 回到第二位
    assert ids[2] == "v5"  # 八达岭 09:30
    assert ids[3] == "meal-lunch-1"
    assert ids[4] == "access-return-v1"
    assert ids[5] == "v6" and ids[6] == "meal-dinner-1"
    # 晨卡钳回首个非酒店卡（07:10）之前
    assert out.days[0].items[0].start_time == time(6, 40)
    assert out.days[0].items[0].end_time == time(7, 10)
    # 非变异：会话本体序与时刻不动
    assert [i.item_id for i in plan.days[0].items] == [
        "hotel-morning-d1",
        "v5",
        "meal-lunch-1",
        "v1",
        "access-return-v1",
        "v6",
        "meal-dinner-1",
        "hotel-night-d1",
    ]
    assert _m(plan.days[0].items[0]) == 8 * 60 + 50


def test_response_clamps_stale_pushed_morning():
    """旧坏快照（用户实锤）：晨卡被推到 08:51 且列表在天安门后 → 响应
    终态晨卡回最前并钳回 06:40（首个非酒店卡 start−30）。"""
    from app.api.plan import _plan_for_response

    anchor = _card("v1", "天安门广场", "attraction", 7 * 60 + 10, 8 * 60 + 40)
    morning = _card(
        "hotel-morning-d2",
        "🏨 从酒店出发",
        "hotel",
        8 * 60 + 51,
        9 * 60 + 21,
        synthetic=True,
        soft_pin=True,
    )
    badaling = _card("v5", "八达岭长城", "historic", 9 * 60 + 51, 12 * 60 + 51)
    night = _card(
        "hotel-night-d1",
        "🏨 回酒店·夜间休息",
        "hotel",
        21 * 60,
        21 * 60 + 30,
        synthetic=True,
        soft_pin=True,
    )
    plan = _plan(anchor, morning, badaling, night)
    out = _plan_for_response(plan)
    items = out.days[0].items
    assert items[0].item_id == "hotel-morning-d2"
    assert items[0].start_time == time(6, 40)
    assert items[-1].item_id == "hotel-night-d1"
    assert items[1].item_id == "v1"  # 天安门紧跟晨卡（其余按时刻）
