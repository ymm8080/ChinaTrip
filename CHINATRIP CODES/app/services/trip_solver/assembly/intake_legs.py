"""行前班次/时刻落腿（2026-11-22「fix all」第二项，bug_summary #3 根修）。

引擎路径此前按 R11 跳过 legacy `_apply_intake_times`：用户表单填的
班次号/时刻只进 C-05 地板/顶盖（时刻语义），**从不落到交通腿上**——
materialize 的腿卡是 8:30/17:00 占位、`train_no/flight_no` 恒空，注释
指向的 `/transfers/{item_id}/tno` 回填端点根本不存在（bug 实证）；
单城/端点行程更连腿都没有。本模块在装配尾把行前信息落到腿上，与
legacy `_pin_intake_leg` 同语义：

- 目标天有城际腿 → 钉：班次号定 mode + train_no/flight_no；用户给了
  时刻 = 到达端（到达侧）/离开端（离开侧），按腿时长反推另一端
  （legacy「班次查库失败回退按时刻」同口径）。
- 目标天无城际腿（单城/端点）→ 合成到达/离开接驳腿（2026-11-22 用户
  拍板「fix all」解除 R11 合成禁令——引擎与 legacy 行前语义拉平）。
- 两侧都没填 → 零动作零披露（「不填=全天游玩」拍板不受影响）。
- 腿时刻与合成晨/夜酒店卡重叠 → 卡撤下（C-13 合成锚让位，legacy 返程
  日无夜卡/到达日无晨卡同形状；模型侧真卡不动）。

只读快照、纯装配：不改模型解的游玩卡时刻（C-05 地板/顶盖已在模型侧
按同一时刻约束过）。
"""

from __future__ import annotations

import re
from datetime import time as _time
from typing import Optional

_TRANSFER_NO_TRAIN_RE = re.compile(r"^[GDCZTKYLS]\d{1,4}$")
_TRANSFER_NO_FLIGHT_RE = re.compile(r"^(?![GDCZTKYLS]\d+$)[A-Z0-9]{2}\d{1,4}[A-Z]?$")

ARRIVAL_DEFAULT_END = 9 * 60 + 30  # legacy 合成到达腿缺省落地 9:30
DEPARTURE_DEFAULT_START = 19 * 60  # legacy 合成离开腿缺省发车 19:00
INTAKE_LEG_MINUTES = 120  # 合成腿时长（legacy 同值）
TRAIN_MINUTES = 120  # 2026-11-18 拍板「火车 2h」
FLIGHT_MINUTES = 150  # 拍板「飞机 2.5h」


def _norm_city(c) -> str:
    return str(c or "").strip().removesuffix("市")


def _detect_kind(number: str) -> str:
    """班次号 → "train" | "flight"；空/不匹配 = ""（agent.plan 同源正则）。"""
    if _TRANSFER_NO_TRAIN_RE.match(number or ""):
        return "train"
    if _TRANSFER_NO_FLIGHT_RE.match(number or ""):
        return "flight"
    return ""


def _hhmm(minutes: int) -> _time:
    minutes = max(0, min(int(minutes), 23 * 60 + 59))
    return _time(minutes // 60 % 24, minutes % 60)


def _m(t) -> Optional[int]:
    if t is None:
        return None
    return t.hour * 60 + t.minute


def _is_leg(item) -> bool:
    return (
        getattr(item, "from_city", None)
        and getattr(item, "to_city", None)
        and _norm_city(item.from_city) != _norm_city(item.to_city)
    )


def _apply_number(leg, number: str) -> None:
    kind = _detect_kind(number)
    if kind == "train":
        leg.mode = "train"
        leg.train_no = number
        leg.flight_no = None
    elif kind == "flight":
        leg.mode = "flight"
        leg.flight_no = number
        leg.train_no = None
    if kind:
        leg.duration_minutes = (
            FLIGHT_MINUTES if kind == "flight" else TRAIN_MINUTES
        )


def _drop_overlapping_synthetic_hotel(plan, day_no: int, lo: int, hi: int) -> bool:
    """合成晨/夜酒店卡与行前腿重叠 → 撤卡（legacy 端点日形状）。
    游玩卡/真酒店卡不动；撤的是 materialize 合成锚（hotel-* 前缀）。"""
    dropped = False

    def _overlap(it) -> bool:
        if str(getattr(it, "category", "") or "") != "hotel":
            return False
        if not getattr(it, "synthetic", False):
            return False
        if not str(getattr(it, "item_id", "") or "").startswith("hotel-"):
            return False
        s = _m(getattr(it, "start_time", None))
        e = _m(getattr(it, "end_time", None))
        if s is None or e is None:
            return False
        return s < hi and e > lo

    for d in plan.days:
        if d.day != day_no:
            continue
        kept = []
        for it in d.items:
            if _overlap(it):
                dropped = True
                continue
            kept.append(it)
        d.items = kept
    return dropped


def _arrival_side(plan, snapshot, notes: list[str]) -> None:
    from ...itinerary.models import TransferItem

    req = snapshot.request
    number = str(getattr(req, "arrival_no", "") or "").strip().upper()
    local = _m(_parse_hhmm(getattr(req, "arrival_time", None)))
    if not number and local is None:
        return  # 两侧都没填：零动作（「不填=全天游玩」拍板）
    day_no = int(getattr(req, "arrival_day", None) or 1)
    day_plan = next((d for d in plan.days if d.day == day_no), None)
    if day_plan is None:
        return
    leg = next(
        (t for t in day_plan.items if isinstance(t, TransferItem) and _is_leg(t)),
        None,
    )
    cities = [c for c in (req.cities or ()) if c]
    if leg is not None:
        if number:
            _apply_number(leg, number)
        if local is not None:
            dur = int(leg.duration_minutes or INTAKE_LEG_MINUTES)
            leg.end_time = _hhmm(local)
            leg.start_time = _hhmm(local - dur)
        _drop_overlapping_synthetic_hotel(
            plan,
            day_no,
            _m(leg.start_time) or 0,
            _m(leg.end_time) or local or ARRIVAL_DEFAULT_END,
        )
        notes.append(
            "第%d天到达已按你填的%s落腿（%s→%s）。"
            % (
                day_no,
                "班次 " + number if number else "时刻",
                leg.from_city,
                leg.to_city,
            )
        )
        return
    # 无腿：合成到达接驳腿（单城/端点，legacy _pin_intake_leg 同形状）
    end = local if local is not None else ARRIVAL_DEFAULT_END
    base = day_plan.base_city
    frm = (
        cities[0]
        if len(cities) >= 2 and _norm_city(cities[0]) != _norm_city(base)
        else "出发地"
    )
    kind = _detect_kind(number)
    new_leg = TransferItem(
        item_id="xfer-intake-arr-d%d" % day_no,
        day=day_no,
        seq=0,
        from_city=frm,
        to_city=base,
        mode=kind or "train",
        start_time=_hhmm(end - INTAKE_LEG_MINUTES),
        end_time=_hhmm(end),
        duration_minutes=INTAKE_LEG_MINUTES,
        train_no=number if kind == "train" else None,
        flight_no=number if kind == "flight" else None,
    )
    day_plan.items.insert(0, new_leg)
    _drop_overlapping_synthetic_hotel(plan, day_no, end - INTAKE_LEG_MINUTES, end)
    stamp = "%02d:%02d" % (end // 60, end % 60)
    notes.append(
        "第%d天到达已按你填的%s合成接驳腿（%s→%s，%s 到达），"
        "当天行程围绕它安排。"
        % (
            day_no,
            "班次 " + number if number else "时刻",
            frm,
            base,
            stamp,
        )
    )


def _departure_side(plan, snapshot, notes: list[str]) -> None:
    from ...itinerary.models import TransferItem

    req = snapshot.request
    number = str(getattr(req, "departure_no", "") or "").strip().upper()
    local = _m(_parse_hhmm(getattr(req, "departure_time", None)))
    if not number and local is None:
        return
    total = len(plan.days)
    day_no = min(int(getattr(req, "departure_day", None) or total), total)
    day_plan = next((d for d in plan.days if d.day == day_no), None)
    if day_plan is None:
        return
    leg = next(
        (
            t
            for t in reversed(day_plan.items)
            if isinstance(t, TransferItem) and _is_leg(t)
        ),
        None,
    )
    cities = [c for c in (req.cities or ()) if c]
    if leg is not None:
        if number:
            _apply_number(leg, number)
        if local is not None:
            dur = int(leg.duration_minutes or INTAKE_LEG_MINUTES)
            leg.start_time = _hhmm(local)
            leg.end_time = _hhmm(local + dur)
        _drop_overlapping_synthetic_hotel(
            plan, day_no, _m(leg.start_time) or 0, _m(leg.end_time) or 24 * 60
        )
        notes.append(
            "第%d天离开已按你填的%s落腿（%s→%s）。"
            % (
                day_no,
                "班次 " + number if number else "时刻",
                leg.from_city,
                leg.to_city,
            )
        )
        return
    base = day_plan.base_city
    to = (
        cities[-1]
        if len(cities) >= 2 and _norm_city(cities[-1]) != _norm_city(base)
        else "返程地"
    )
    kind = _detect_kind(number)
    start = local if local is not None else DEPARTURE_DEFAULT_START
    new_leg = TransferItem(
        item_id="xfer-intake-dep-d%d" % day_no,
        day=day_no,
        seq=1,
        from_city=base,
        to_city=to,
        mode=kind or "train",
        start_time=_hhmm(start),
        end_time=_hhmm(start + INTAKE_LEG_MINUTES),
        duration_minutes=INTAKE_LEG_MINUTES,
        train_no=number if kind == "train" else None,
        flight_no=number if kind == "flight" else None,
    )
    day_plan.items.append(new_leg)
    _drop_overlapping_synthetic_hotel(plan, day_no, start, start + INTAKE_LEG_MINUTES)
    stamp = "%02d:%02d" % (start // 60, start % 60)
    notes.append(
        "第%d天离开已按你填的%s合成接驳腿（%s→%s，%s 出发）。"
        % (day_no, "班次 " + number if number else "时刻", base, to, stamp)
    )


def _parse_hhmm(text) -> Optional[_time]:
    """「HH:MM」（全角冒号/点分隔同 legacy _parse_hm 口径）；读不出 None。"""
    s = str(text or "").strip().replace("：", ":").replace(".", ":")
    m = re.match(r"^(\d{1,2}):(\d{1,2})$", s)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return _time(h, mi)


def apply_intake_legs(plan, snapshot) -> list[str]:
    """装配尾入口：把行前班次/时刻落到腿上（见模块 docstring）。

    返回披露行（并入 plan.assumptions）；任何失败只丢披露不抛——
    行前落位是 best-effort（legacy 同语义），绝不把主流程打成 500。"""
    notes: list[str] = []
    try:
        _arrival_side(plan, snapshot, notes)
    except Exception:  # noqa: BLE001 - best-effort（legacy 同语义）
        notes.append("到达班次/时刻落位失败，已保持引擎原计划。")
    try:
        _departure_side(plan, snapshot, notes)
    except Exception:  # noqa: BLE001 - best-effort
        notes.append("离开班次/时刻落位失败，已保持引擎原计划。")
    if notes:
        try:
            from ...itinerary.legs import annotate_legs

            annotate_legs(plan)  # 腿时刻变了 → 显示腿重算（幂等）
        except Exception:  # noqa: BLE001 - 显示层失败不拦交付
            pass
    return notes
