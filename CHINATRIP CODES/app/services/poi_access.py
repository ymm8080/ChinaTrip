"""POI 到达方式摘要（2026-11-15 用户拍板「远郊景点要有交通方式」）。

城心 → POI 的公共交通方案（``transit_route`` 形状，见
:meth:`app.services.amap_client.AmapClient.transit_route`，百度链同形）归一
成 ``pois.access_*`` 一组摘要列：

* ``access_mode``：metro / bus / train / shuttle / ferry / walk
* ``access_minutes``：门到门参考时长（城心出发，含步行与换乘）
* ``access_gateway``：最后一段车的下车站（火车/专线都不停在景区门口）
* ``access_gateway_minutes``：下车后步行分钟
* ``access_note`` / ``access_note_en``：一句人话（含首末班——景区直达车
  末班 12:00 这类信息直接决定当天能不能去）

为什么是「城心口径的摘要」而不是精确路由：同一 POI 从酒店/上一站出发的
走法由导航端点现算；本组列只回答「这地方大概怎么去、要多久、有没有班次」，
供站点卡展示与引擎粗判（远郊件/需班次件）。精确到分钟的接驳腿属二期，
由 ``poi_access`` 明细表 + solver 承接。
"""

from __future__ import annotations

from typing import Any

#: 出行方式排序（取「主干那一段」用）：数字越大越算主干。
MODE_RANK: dict[str, int] = {
    "walk": 0,
    "bus": 1,
    "metro": 2,
    "ferry": 3,
    "shuttle": 4,
    "train": 5,
}

MODE_LABEL_ZH: dict[str, str] = {
    "walk": "步行",
    "bus": "公交",
    "metro": "地铁",
    "shuttle": "景区专线",
    "ferry": "轮渡",
    "train": "铁路",
}

#: 线路名 → 方式的判定词（先于 kind 判，跨图商最稳；百度 type 字段
#: 语义在 0/1/10 之外不可靠）。顺序有讲究：地铁先于专线（「地铁8号线」），
#: 景区专线先于铁路（「景区直达车」偶带「铁路」字样）。
_METRO_TOKENS = ("地铁", "号线", "轻轨", "有轨电车", "metro", "subway")
_SHUTTLE_TOKENS = (
    "景区直达",
    "直达车",
    "直通车",
    "专线",
    "接驳",
    "直通",
    "旅游线",
    "观光车",
    "shuttle",
)
_FERRY_TOKENS = ("轮渡", "游船", "客船", "ferry")
_TRAIN_TOKENS = ("铁路", "城际", "高铁", "动车", "市郊", "城铁", "火车", "rail")


def classify_ride(ride: dict[str, Any]) -> str:
    """一段乘车 → 出行方式（metro/bus/train/shuttle/ferry）。"""
    name = str(ride.get("name") or "")
    low = name.lower()
    if any(tok in name or tok in low for tok in _METRO_TOKENS):
        return "metro"
    if any(tok in name or tok in low for tok in _SHUTTLE_TOKENS):
        return "shuttle"
    if any(tok in name or tok in low for tok in _FERRY_TOKENS):
        return "ferry"
    if any(tok in name or tok in low for tok in _TRAIN_TOKENS):
        return "train"
    return "train" if str(ride.get("kind") or "") == "railway" else "bus"


def _seq(plan: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """方案 → 有序的 (kind, 对象) 序列（walk / ride 交替，保留原始顺序）。"""
    out: list[tuple[str, dict[str, Any]]] = []
    for seg in plan.get("segments") or []:
        if not isinstance(seg, dict):
            continue
        walking = seg.get("walking")
        if isinstance(walking, dict):
            out.append(("walk", walking))
        for ride in seg.get("rides") or []:
            if isinstance(ride, dict):
                out.append(("ride", ride))
    return out


def _minutes(seconds: object) -> int:
    try:
        return max(0, round(int(seconds) / 60))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _fmt_minutes(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} 分钟"
    hours, mins = divmod(minutes, 60)
    return f"{hours} 小时" + (f" {mins} 分" if mins else "")


def _fmt_minutes_en(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} min"
    hours, mins = divmod(minutes, 60)
    return f"{hours} h" + (f" {mins} min" if mins else "")


def _fmt_clock(value: object) -> str | None:
    text = str(value or "").strip()
    return text if len(text) == 5 and text[2] == ":" else None


def _rides(seq: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    return [obj for kind, obj in seq if kind == "ride"]


def _trailing_walk(seq: list[tuple[str, dict[str, Any]]]) -> tuple[int, int]:
    """最后一段车之后的步行（分钟, 米）——下车到景区门口。"""
    minutes = 0
    meters = 0
    for kind, obj in reversed(seq):
        if kind == "ride":
            break
        minutes += _minutes(obj.get("duration_s"))
        try:
            meters += max(0, int(obj.get("distance_m") or 0))
        except (TypeError, ValueError):
            pass
    return minutes, meters


#: 下车点到景区门口超过这个距离就不叫「步行」了（龙门涧实录：柏峪村站
#: 到景区门口 13km，写成「下车步行 166 分钟」是误导）。
TAXI_PICKUP_METERS = 1500


def _primary_ride(rides: list[dict[str, Any]]) -> dict[str, Any] | None:
    """主干那一段：时长最长的一段（缺时长时按方式重要性兜底）。

    口径：远郊件的「怎么去」问的是那趟把人和城心拉开距离的车——地铁
    40 分钟 + 长途公交 2 小时报公交，不是报地铁。
    """
    if not rides:
        return None
    timed = [r for r in rides if _minutes(r.get("duration_s")) > 0]
    if timed:
        return max(
            timed,
            key=lambda r: (
                _minutes(r.get("duration_s")),
                MODE_RANK.get(classify_ride(r), 0),
            ),
        )
    return max(rides, key=lambda r: MODE_RANK.get(classify_ride(r), 0))


def _time_window(ride: dict[str, Any] | None) -> tuple[str | None, str | None]:
    """主干段的首末班（景区直达车/铁路才有；公交表不一定给）。"""
    if not ride:
        return None, None
    first = _fmt_clock(ride.get("departure_time"))
    last = _fmt_clock(ride.get("last_time"))
    table = ride.get("time_table")
    if isinstance(table, list) and table:
        clocks = [c for c in (_fmt_clock(x) for x in table) if c]
        if clocks:
            first = first or min(clocks)
            last = last or max(clocks)
    return first, last


def build_note(
    rides: list[dict[str, Any]],
    *,
    total_minutes: int,
    walk_minutes: int,
    gateway: str | None,
    walk_meters: int = 0,
) -> tuple[str, str]:
    """一句人话（zh, en）——不硬编码任何具体景点名。"""
    if not rides:
        zh = f"步行可达，约 {_fmt_minutes(total_minutes)}"
        en = f"Walkable, about {_fmt_minutes_en(total_minutes)}"
        return zh, en

    first, last = rides[0], rides[-1]
    names = [str(r.get("name") or "").strip() for r in rides]
    names = [n for n in names if n]
    board = str(first.get("departure_stop") or "").strip()
    alight = str(gateway or last.get("arrival_stop") or "").strip()
    transfers = max(0, len(rides) - 1)

    main = _primary_ride(rides)
    first_time, last_time = _time_window(main)

    if len(rides) == 1:
        zh = f"乘 {names[0]}" if names else "乘车"
        en = f"Take {names[0]}" if names else "Take transit"
    else:
        shown = names if len(names) <= 3 else (names[:2] + ["…", names[-1]])
        chain = " → ".join(shown)
        zh = f"乘 {chain}（{transfers} 次换乘）" if chain else f"换乘 {transfers} 次"
        plural = "s" if transfers > 1 else ""
        en = (
            f"Take {chain} ({transfers} transfer{plural})"
            if chain
            else f"{transfers} transfer{plural}"
        )

    if board and alight:
        zh += f"：{board} → {alight}"
        en += f": {board} → {alight}"
    elif alight:
        zh += f"，{alight} 下车"
        en += f", alight at {alight}"

    if first_time or last_time:
        if first_time and last_time and first_time == last_time:
            # 一日一班的通勤/景区班车：写成「首班=末班」会误导成全天有车
            zh += f"（仅 {first_time} 一班）"
            en += f" (only {first_time})"
        else:
            bits = []
            if first_time:
                bits.append(f"首班 {first_time}")
            if last_time:
                bits.append(f"末班 {last_time}")
            zh += "（" + " / ".join(bits) + "）"
            eb = []
            if first_time:
                eb.append(f"first {first_time}")
            if last_time:
                eb.append(f"last {last_time}")
            en += " (" + " / ".join(eb) + ")"

    zh += f"，全程约 {_fmt_minutes(total_minutes)}"
    en += f", about {_fmt_minutes_en(total_minutes)}"
    if walk_meters >= TAXI_PICKUP_METERS:
        km = walk_meters / 1000.0
        zh += f"，下车点距景区约 {km:.1f} km，末段建议打车/接驳"
        en += f", the stop is ~{km:.1f} km from the gate — take a taxi the last leg"
    elif walk_minutes >= 5:
        zh += f"，下车步行 {walk_minutes} 分钟"
        en += f", {walk_minutes} min walk from the stop"
    return _clamp(zh), _clamp(en)


def _clamp(text: str, limit: int = 300) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def summarize(plans: list[Any] | None) -> dict[str, Any] | None:
    """转乘方案组 → ``pois.access_*`` 写入值（取最快的一条）。

    返回 ``None`` = 无法判定（无方案/无时长），调用方跳过不写。
    """
    usable = [
        plan
        for plan in (plans or [])
        if isinstance(plan, dict) and _minutes(plan.get("duration_s")) > 0
    ]
    if not usable:
        return None
    plan = min(usable, key=lambda p: _minutes(p.get("duration_s")))
    total_minutes = _minutes(plan.get("duration_s"))
    seq = _seq(plan)
    rides = _rides(seq)

    if not rides:
        mode = "walk"
        gateway = None
        gateway_minutes = 0
        gateway_meters = 0
    else:
        primary = _primary_ride(rides)
        mode = classify_ride(primary) if primary else "bus"
        gateway = str(rides[-1].get("arrival_stop") or "").strip() or None
        gateway_minutes, gateway_meters = _trailing_walk(seq)

    note, note_en = build_note(
        rides,
        total_minutes=total_minutes,
        walk_minutes=gateway_minutes,
        gateway=gateway,
        walk_meters=gateway_meters,
    )
    # 下车点离景区口太远时，那几分钟不是「步行」而是需要接驳/打车，别把它
    # 当步行分钟报给卡片（龙门涧实录：166 分钟「步行」实际是 13km 山路）。
    walkable = gateway_meters < TAXI_PICKUP_METERS
    return {
        "access_mode": mode,
        "access_minutes": total_minutes,
        "access_gateway": _clamp(gateway or "", 100) or None,
        "access_gateway_minutes": gateway_minutes if walkable else None,
        "access_note": note,
        "access_note_en": note_en,
    }
