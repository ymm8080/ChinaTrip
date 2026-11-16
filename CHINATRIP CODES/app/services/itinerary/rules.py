"""Iron-rule hard validators for the itinerary mutation pipeline (design §6.0/§6.4).

Server-checkable subset of iron rules 0-23. Every validator is a pure
function over the shared domain models — no I/O, no LLM, no DB.

铁律归属映射表（哪条在哪儿管）:

本模块（rules.py）校验:
    1 时间冲突（同日 VisitItem 区间重叠）→ validate_plan
    2 营业时间（超 poi_hours 窗口；无数据跳过）→ validate_plan
    3 地理自洽·简化（城市归属 / base_city 跳变）→ validate_plan
    4 跨城衔接缓冲（VisitItem↔TransferItem ≥90 分钟）→ validate_plan
    5 同日多段跨城（seq 递增唯一 + 互相缓冲）→ validate_plan
    6 节奏量化（日步行 ≤15km×人群系数；游览占比 ≥55%）→ validate_plan
    7 相邻对象对间隔 ≥ 打车腿（零车程背靠背绊网；2026-11-13 起餐/
      酒店/钉件同口径，仅同址≤SAME_VENUE_KM 与无坐标对豁免）→ validate_plan
    10 只动当天及之后 → validate_change_scope
    19 钉死点（pinned 不得被移动/改时间/删除）→ validate_pinned

不归本校验器管（服务端纯函数无法判定，归属如下）:
    0 一切变更走统一 diff 管线 → pipeline.mutate（本包）
    8 3 秒延迟预算 → API 网关 / 性能监控（非行程域）
    9 重排带 reasoning → Agent 输出层填 ChangeSummary.reasoning
    11 执行模式不动过去（生成端）→ 执行模式会话编排层
    12 同步端不覆盖过去 → 多端同步服务
    13 时区以行程城市为准 → 客户端时区服务（本模块时间为本地时间）
    14 解析期 LLM 零写权限 → 解析阶段工具白名单（无行程写入工具）
    15 不可信内容 quarantine → extraction.py::scan_injection
    16 快照不可变，恢复只写工作副本 → 快照服务（只读恢复）
    17 执行中切换执行版 = 受限重排 → 执行版管理（复用 from_day 语义）
    18 离线禁止切到未下载离线包的版本 → 客户端离线包管理
    20 餐饮插入不挤占核心游览 → recommend_restaurants 工具
    21 语音/图片数据本地闭环 → 独立语音服务（§6.10，禁云 API）
    22 行动只 handoff 不代客交易 → 行动编排层（仅出 deeplink）
    23 退改签透明前置（无摘要禁止跳转）→ handoff 确认卡片渲染层
"""

from datetime import time
from math import asin, cos, radians, sin, sqrt

from app.services.itinerary.models import (
    CROWD_COEF_MAX,
    CROWD_COEF_MIN,
    INTERCITY_BUFFER_MINUTES,
    VALID_TOUR_RATIO_MIN,
    WALK_KM_PER_DAY_MAX,
    CrowdProfile,
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    PoiHours,
    RuleSeverity,
    RuleViolation,
    TransferItem,
    ValidationReport,
    VisitItem,
)
from app.services.itinerary.solver import (
    AFTERNOON_START_MINUTES,
    SAME_VENUE_KM,
    _is_big_site,
    fusion_food_nested,
    generic_entry_cap,
)
from app.services.lang_ctx import L

# Iron rule 6 crowd coefficient band (models.py pins the 0.6-1.2 bounds).
CROWD_COEFFICIENTS: dict[CrowdProfile, float] = {
    CrowdProfile.slow: CROWD_COEF_MIN,
    CrowdProfile.normal: 1.0,
    CrowdProfile.fast: CROWD_COEF_MAX,
}

_EARTH_RADIUS_KM = 6371.0


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _fmt(t: time | None) -> str:
    return t.strftime("%H:%M") if t is not None else "?"


def _norm_city(name: str) -> str:
    # LLM 写 POI city 常带后缀（"杭州市"/"上海市"），用户输入行程城市不带——
    # 归一化后再比较，否则规则 3 对合法行程满屏假警告。
    name = name.strip()
    return name[:-1] if name.endswith("市") else name


def haversine_km(a: GeoPoint, b: GeoPoint) -> float:
    lat1, lat2 = radians(a.lat), radians(b.lat)
    dlat, dlon = lat2 - lat1, radians(b.lon) - radians(a.lon)
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2.0 * _EARTH_RADIUS_KM * asin(sqrt(h))


# 打车模型常量（2026-11-14 用户拍板：车速 70km/h 城市均速、叫车等待 15 分钟；
# 此前 35km/h + 30 分钟，把 57km 的慕田峪→市区算成 2 小时）：
# 车程=直线×1.3 绕行 ÷ 70km/h，另加 15 分钟叫车/等待；≤1.5km 近距共址按
# 步行（不白付叫车开销）；单腿上限 180 分钟。选点腿费/必去放日/solver
# 矩阵/兜底锚窗四家共用 taxi_leg_min，调用点不得另算口径。
TRAVEL_LEG_CAP_MIN = 180
TAXI_HAIL_MINUTES = 15
TAXI_MIN_PER_KM = 1.3 / 70 * 60  # ≈1.11 分钟/公里（直线×绕行÷70km/h）
TAXI_WALK_MAX_KM = 1.5  # 此距内步行更合理，不打车
#: 步行估算分钟/公里（×1.3 绕行 / 80m/min）——近距腿与卡片展示共用。
TRAVEL_MIN_PER_KM = 1000.0 * 1.3 / 80.0

#: 相邻观光对的最小间隔地板（无坐标/毒坐标对的保守值）。
TRAVEL_GAP_FLOOR_MIN = 30


def taxi_leg_min(km: float) -> int:
    """点间走行分钟（打车模型，用户拍板 2026-10-31）：车程+半小时叫车；
    ≤1.5km 近距退步行口径；封顶 TRAVEL_LEG_CAP_MIN。"""
    if km <= TAXI_WALK_MAX_KM:
        return round(km * TRAVEL_MIN_PER_KM)
    return min(TRAVEL_LEG_CAP_MIN, round(km * TAXI_MIN_PER_KM) + TAXI_HAIL_MINUTES)


#: 有班次接驳的到达方式：这几种点按「打车到乘车点 + 候车 + 班次 + 落客」算腿。
SCHEDULED_ACCESS_MODES = ("train", "shuttle", "ferry")


def _access_profile(b: VisitItem) -> tuple[str | None, GeoPoint | None, int, int, int]:
    """b 的接驳量：卡上字段优先；没有就按 (city, name) 查一次城市档案。

    为什么要有第二来源：solver 矩阵会先 attach 档案，但心愿快路径 / 兜底
    重排 / 单点加卡都不经过矩阵——同一天不能出现两套腿口径。
    """
    mode = b.access_mode
    boarding = b.access_boarding
    service = b.access_service_minutes or 0
    wait = b.access_wait_minutes or 0
    last = b.access_last_mile_minutes or 0
    if (mode is None or boarding is None or not service) and b.name:
        try:
            from app.services.poi_access import profile_for

            prof = profile_for(getattr(b, "city", None), b.name) or {}
        except Exception:  # noqa: BLE001 — 档案不可用=打车兜底
            prof = {}
        if prof:
            mode = mode or prof.get("access_mode")
            service = service or prof.get("access_service_minutes") or 0
            wait = prof.get("access_wait_minutes") or 0
            last = prof.get("access_last_mile_minutes") or 0
            lon = prof.get("access_boarding_lon")
            lat = prof.get("access_boarding_lat")
            if lon is not None and lat is not None:
                boarding = GeoPoint(lon=float(lon), lat=float(lat))
    return mode, boarding, service, wait, last


def _is_morning_hotel(item: VisitItem) -> bool:
    """当天「从酒店出发」晨卡（占位，id=hotel-morning-dN）。"""
    return str(getattr(item, "item_id", "") or "").startswith("hotel-morning")


def _hhmm_minutes(text: str | None) -> int | None:
    """'09:30' → 570；脏值返回 None。"""
    raw = str(text or "").strip().replace("：", ":")
    if ":" not in raw:
        return None
    head, _, tail = raw.partition(":")
    try:
        hour, minute = int(head), int(tail[:2])
    except (TypeError, ValueError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


def _fastest_ride(
    city: str | None,
    name: str | None,
    board: int | None,
    ride_fallback: int,
    last_fallback: int,
    departures: list[str] | None = None,
) -> tuple[int | None, int, int, int]:
    """挑「到景区最早」的一班（与 access_services.fastest_plan 同一口径）。

    没有官方时刻表时回落档案经验值（发车=None、候车用档案值）。
    """
    if board is None:
        board = 9 * 60  # 无前件时刻：用户口径「远郊专线通常 9 点前后」
    try:
        from app.services import access_services

        got = access_services.fastest_plan(
            city,
            name,
            board,
            ride_fallback=ride_fallback,
            last_fallback=last_fallback,
        )
    except Exception:  # noqa: BLE001 - 班次库不可用=档案经验值
        got = None
    if got is None:
        # 班次库不可用：退回卡上自带的官方时刻表（同一「最快到景区」口径）
        times = [
            m for m in (_hhmm_minutes(t) for t in (departures or [])) if m is not None
        ]
        nxt = next((t for t in sorted(times) if t >= board), None)
        if nxt is None:
            return None, ride_fallback, last_fallback, 0
        return nxt, ride_fallback, last_fallback, nxt - board
    depart, ride, last, wait = got
    return depart, ride, last, wait


def _fastest_return_ride(
    a: VisitItem, board: int, ride_fallback: int
) -> tuple[int | None, int, int | None]:
    """挑「离开景区后最快回市区」的一班（fastest_return_plan 同口径）。

    返回 (发车, 车上分钟, 候车分钟)；班次库不可用且卡上没有返程时刻表
    → (None, ride_fallback, None)（候车由调用方退档案经验值）。
    """
    try:
        from app.services import access_services

        got = access_services.fastest_return_plan(
            getattr(a, "city", None), a.name, board, ride_fallback=ride_fallback
        )
    except Exception:  # noqa: BLE001 - 班次库不可用=档案经验值
        got = None
    if got is not None:
        return got
    # 班次库不可用：退回卡上自带的官方返程时刻表（同一「最快回城」口径）
    times = [
        m
        for m in (
            _hhmm_minutes(t) for t in (getattr(a, "access_return_times", None) or [])
        )
        if m is not None
    ]
    nxt = next((m for m in sorted(times) if m >= board), None)
    if nxt is None:
        return None, ride_fallback, None
    return nxt, ride_fallback, nxt - board


def _return_breakdown(a: VisitItem, b: VisitItem) -> dict | None:
    """a（班次点或锚在其上的占位卡）→ b（市区下一站）的回城返向链。

    2026-11-16 用户拍板「回城也是一样的接驳三段」：步行回乘车点 →
    候返程班 → 专线回市区落点 → 打车到下一站。没有官方返程时刻表时
    候车退档案经验值（发车=None）。b 也是班次点时不走这里（去程优先）。
    """
    mode, terminal, service, wait, last = _access_profile(a)
    if mode not in SCHEDULED_ACCESS_MODES or terminal is None or not service:
        return None
    front = int(getattr(a, "access_last_mile_minutes", None) or last or 0)
    a_end = None
    if getattr(a, "end_time", None) is not None:
        a_end = a.end_time.hour * 60 + a.end_time.minute
    elif getattr(a, "start_time", None) is not None:
        a_end = (
            a.start_time.hour * 60
            + a.start_time.minute
            + int(getattr(a, "duration_minutes", None) or 0)
        )
    board = a_end + front if a_end is not None else None
    ride = int(getattr(a, "access_ride_minutes", None) or service)
    depart: int | None = None
    wait_minutes: int | None = None
    if board is not None:
        depart, ride, wait_minutes = _fastest_return_ride(a, board, ride)
    if wait_minutes is None:
        wait_minutes = wait
    b_loc = b.location or getattr(b, "anchor_location", None)
    taxi_km = 0.0
    taxi_minutes = 0
    if b_loc is not None:
        taxi_km = haversine_km(terminal, b_loc)
        taxi_minutes = taxi_leg_min(taxi_km)
    minutes = max(
        TRAVEL_GAP_FLOOR_MIN,
        front + (wait_minutes or 0) + ride + taxi_minutes,
    )
    return {
        "mode": mode,
        "minutes": minutes,
        "taxi_km": taxi_km,
        "taxi_minutes": taxi_minutes,
        "wait": max(0, wait_minutes or 0),
        "service": ride,
        "last": front,
        "board": board,
        "depart": depart,
        "direction": "return",
    }


def access_breakdown(a: VisitItem, b: VisitItem) -> dict | None:
    """a → b 的接驳链拆分（2026-11-16 用户拍板「显示打车段/专线/步行」）。

    打车到乘车点（距离/分钟）→ 候车 → 专线车程 → 落客步行；班次按
    「到站后最快到景区」挑（没有官方时刻表才用档案经验值）。
    b 不是班次点而 a 是（或锚在其上的占位卡）→ 返向回城链
    （_return_breakdown，同拍板「回城也是一样的接驳三段」）。
    """
    mode, boarding, service, wait, last = _access_profile(b)
    if mode not in SCHEDULED_ACCESS_MODES:
        # b 不是班次点：a 是班次点（或锚在其上的占位卡）→ 回城返向链；
        # a 也不是班次点 → None，走打车模型。
        return _return_breakdown(a, b)
    _from = a.location or getattr(a, "anchor_location", None)
    if _from is None or boarding is None or not service:
        return None
    taxi_km = haversine_km(_from, boarding)
    head = taxi_leg_min(taxi_km)
    a_end = None
    if getattr(a, "end_time", None) is not None:
        a_end = a.end_time.hour * 60 + a.end_time.minute
    elif getattr(a, "start_time", None) is not None:
        a_end = (
            a.start_time.hour * 60
            + a.start_time.minute
            + int(getattr(a, "duration_minutes", None) or 0)
        )
    # 晨卡（「从酒店出发」占位，08:30-09:00 打包窗口）不是真的在酒店玩半小时：
    # 排期口径一直是「接驳链从晨卡开始时打」，这里对齐，免得卡上时间比腿短 30 分钟。
    if _is_morning_hotel(a) and getattr(a, "start_time", None) is not None:
        a_end = a.start_time.hour * 60 + a.start_time.minute
    # 无前件时刻：用户口径「远郊专线通常 9 点前后」（此时不再叠加打车段，
    # 与既有 fastest_plan 口径一致）；有前件时刻才按「前件结束 + 打车到乘车点」。
    if a_end is not None:
        a_end_min = a_end
        add_head = True
    else:
        a_end_min = 9 * 60
        add_head = False

    def _taxi_to(coords):
        # 各方式自己的乘车点坐标 → 打车分钟；无坐标回档案乘车点的打车段
        if not add_head:
            return 0
        if not coords:
            return head
        return taxi_leg_min(
            haversine_km(_from, GeoPoint(lon=float(coords[0]), lat=float(coords[1])))
        )

    # 2026-11-16 用户拍板「不同方式分 BLOCK 并排，默认换乘少+时间短」：
    # 每个官方班次行出一块，排序 (换乘, 全程, 票价)，腿时间与推荐块同口径。
    options: list[dict] = []
    try:
        from app.services import access_services

        options = access_services.service_options(
            getattr(b, "city", None),
            b.name,
            board_minutes=a_end_min,
            ride_fallback=service,
            last_fallback=last,
            wait_fallback=wait,
            taxi_minutes=_taxi_to,
        )
    except Exception:  # noqa: BLE001 - 班次库不可用=档案经验值
        options = []
    if options:
        opt = options[0]
        head = int(opt.get("taxi_minutes") or 0)
        if opt.get("boarding_lon") is not None and opt.get("boarding_lat") is not None:
            boarding = GeoPoint(
                lon=float(opt["boarding_lon"]), lat=float(opt["boarding_lat"])
            )
            taxi_km = haversine_km(_from, boarding)
        depart = _hhmm_minutes(opt.get("depart"))
        ride = int(opt.get("ride_minutes") or 0)
        last_mile = int(opt.get("last_mile_minutes") or 0)
        wait_minutes = int(opt.get("wait_minutes") or 0)
        board = a_end_min + head
    else:
        board = (a_end + head) if a_end is not None else 9 * 60
        depart, ride, last_mile, wait_minutes = _fastest_ride(
            getattr(b, "city", None),
            b.name,
            board,
            service,
            last,
            getattr(b, "access_depart_times", None),
        )
        if depart is None:
            # 没有官方时刻表：沿用卡上档案（车上分钟 + 经验候车）
            ride, last_mile, wait_minutes = service, last, wait
    minutes = max(
        TRAVEL_GAP_FLOOR_MIN,
        head + (wait_minutes or 0) + ride + last_mile,
    )
    return {
        "mode": mode,
        "minutes": minutes,
        "taxi_km": taxi_km,
        "taxi_minutes": head,
        "wait": max(0, wait_minutes or 0),
        "service": ride,
        "last": last_mile,
        "board": board,
        "depart": depart,
        "fare_cny": (
            options[0].get("fare_cny")
            if options
            else None
        ),
        "options": options,
    }


def access_chain_minutes(a: VisitItem, b: VisitItem) -> int | None:
    """a 鈫?b 的接驳链分钟；b 不是班次点或缺接驳量时返回 None（走打车模型）。"""
    got = access_breakdown(a, b)
    return got["minutes"] if got else None


def travel_gap_needed(a: VisitItem, b: VisitItem) -> int | None:
    """相邻两点 a→b 需要的走行分钟。

    2026-11-13 用户拍板「路途时间和距离在所有 OBJECT 里都要正确计算
    （HOTEL/餐饮/活动/景点）」：旧按类目豁免（餐/酒店贴点、钉点）是
    「同址」的粗糙代理，撤除——改为距离语义：

    - 双方有坐标且同址（≤SAME_VENUE_KM）：返回 None——同址嵌套/并
      块尾（2026-11-12/11-10 拍板）按真实距离天然免隔腿，不再按类目
      一刀切；
    - 双方有坐标：max(TRAVEL_GAP_FLOOR_MIN, taxi_leg_min(km))——
      餐/酒店/钉件与观光件同口径（秦俑情 11:00 散场→41km 外餐厅
      12:20 零车程案：钉不可挪由铁律 19 管移动，本条管间隔计算与披露）；
    - 任一方无坐标：返回 None（算不出），调用方须留痕；例外=锚在
      班次点上的占位卡（继承档案后按回城返向链算，2026-11-16）。
    口径与兜底 _leg_windows 的 pad 一致：max(30, taxi_leg_min(haversine))。
    """
    b_loc = b.location
    if b_loc is None:
        return None
    a_loc = a.location
    if a_loc is None:
        # 锚定占位卡（午饭/晚饭）自己没有坐标：仅当锚在班次点上（继承
        # 了接驳档案）时回城返向链才成立（2026-11-16「回城三段」）；
        # 其余锚卡维持 None，不放大豁免口径。
        mode_a, _terminal, service_a, _wait_a, _last_a = _access_profile(a)
        if mode_a not in SCHEDULED_ACCESS_MODES or not service_a:
            return None
        a_loc = getattr(a, "anchor_location", None)
        if a_loc is None:
            return None
    km = haversine_km(a_loc, b_loc)
    if km <= SAME_VENUE_KM:
        return None  # 同址不隔腿（嵌套/并块尾按距离语义豁免）
    chain = access_chain_minutes(a, b)
    if chain is not None:
        # 班次点（景区专线/市郊铁路/轮渡）：打车直达口径换成接驳链，排期
        # 才排得下——慕田峪打车 81 分钟、实际专线 2 小时 15 分。
        return chain
    return max(TRAVEL_GAP_FLOOR_MIN, taxi_leg_min(km))


def _eff_end_minutes(item: VisitItem | TransferItem) -> int | None:
    """end_time in minutes-of-day, or start+duration when end missing."""
    if item.end_time is not None:
        return _minutes(item.end_time)
    if item.start_time is not None and item.duration_minutes is not None:
        return _minutes(item.start_time) + item.duration_minutes
    return None


def _report(violations: list[RuleViolation]) -> ValidationReport:
    has_error = any(v.severity == RuleSeverity.error for v in violations)
    return ValidationReport(ok=not has_error, violations=violations)


# --- iron rule 1: same-day VisitItem time overlap -------------------------


def _nested_food_pair(a: VisitItem, b: VisitItem) -> bool:
    """同址餐饮融合嵌套（2026-11-12 用户拍板「街区天然有餐饮，不应该互斥
    相撞...街区的时间里包含了餐厅时间」）：food 卡完整落在同址（≤
    SAME_VENUE_KM）宿主卡窗内=时间包含语义，不判铁律 1 双订。判定定义
    点 solver.fusion_food_nested；部分溢出/非同址照旧报错。"""
    return fusion_food_nested(
        a,
        b,
        (_minutes(a.start_time), _minutes(a.end_time)),
        (_minutes(b.start_time), _minutes(b.end_time)),
    )


def _check_time_conflicts(day_no: int, visits: list[VisitItem]) -> list[RuleViolation]:
    timed = sorted(
        (v for v in visits if v.start_time is not None and v.end_time is not None),
        key=lambda v: (v.start_time, v.end_time),
    )
    out = []
    for prev, cur in zip(timed, timed[1:]):
        if _minutes(prev.end_time) > _minutes(cur.start_time):
            if _nested_food_pair(prev, cur):
                continue  # 同址餐饮融合豁免（拍板）：街区时间包含餐厅时间
            out.append(
                RuleViolation(
                    rule_id=1,
                    severity=RuleSeverity.error,
                    message=L(
                        f"第{day_no}天 {prev.name}({_fmt(prev.start_time)}-"
                        f"{_fmt(prev.end_time)}) 与 {cur.name}({_fmt(cur.start_time)}-"
                        f"{_fmt(cur.end_time)}) 时间区间重叠",
                        f"Day {day_no}: {prev.name}({_fmt(prev.start_time)}-"
                        f"{_fmt(prev.end_time)}) and {cur.name}({_fmt(cur.start_time)}-"
                        f"{_fmt(cur.end_time)}) time ranges overlap",
                    ),
                    item_ids=[prev.item_id, cur.item_id],
                    day=day_no,
                )
            )
    return out


# --- iron rule 7: consecutive sight pairs must allow the taxi leg ---------


def travel_gap_violations(day_no: int, visits: list[VisitItem]) -> list[RuleViolation]:
    """零车程背靠背绊网（2026-11-03 Day2 大明宫→城墙 15:00 事故）：
    相邻已排对象对的间隔必须 ≥ 打车腿（无坐标对 ≥30 地板）。豁免口径
    见 travel_gap_needed（2026-11-13 起仅同址/无坐标豁免，餐/酒店/钉
    件照算——solver 生成端漏网由此处披露兜底）。"""
    timed = sorted(
        (v for v in visits if v.start_time is not None and v.end_time is not None),
        key=lambda v: (v.start_time, v.end_time),
    )
    out: list[RuleViolation] = []
    for prev, cur in zip(timed, timed[1:]):
        need = travel_gap_needed(prev, cur)
        if need is None:
            continue
        gap = _minutes(cur.start_time) - _minutes(prev.end_time)
        if gap < need:
            out.append(
                RuleViolation(
                    rule_id=7,
                    severity=RuleSeverity.error,
                    message=L(
                        f"第{day_no}天 {prev.name} {_fmt(prev.end_time)} 散场到"
                        f" {cur.name} {_fmt(cur.start_time)} 开场仅 {gap} 分钟，"
                        f"打车约需 {need} 分钟（未计路上时间）",
                        f"Day {day_no}: only {gap} min between {prev.name} "
                        f"ending {_fmt(prev.end_time)} and {cur.name} starting "
                        f"{_fmt(cur.start_time)} — taxi needs ~{need} min",
                    ),
                    item_ids=[prev.item_id, cur.item_id],
                    day=day_no,
                )
            )
    return out


# --- iron rule 2: opening hours -------------------------------------------


def _check_opening_hours(
    day_no: int, visits: list[VisitItem], hours: dict[str, PoiHours]
) -> list[RuleViolation]:
    out = []
    for v in visits:
        h = hours.get(v.poi_id) if v.poi_id else None
        if h is None:
            continue  # 无营业时间数据，跳过（铁律 2 口径）
        bad_start = v.start_time is not None and v.start_time < h.opens
        bad_end = v.end_time is not None and v.end_time > h.closes
        if bad_start or bad_end:
            out.append(
                RuleViolation(
                    rule_id=2,
                    severity=RuleSeverity.error,
                    message=L(
                        f"第{day_no}天 {v.name}"
                        f"({_fmt(v.start_time)}-{_fmt(v.end_time)})"
                        f"超出营业时间 {_fmt(h.opens)}-{_fmt(h.closes)}",
                        f"Day {day_no}: {v.name}({_fmt(v.start_time)}-"
                        f"{_fmt(v.end_time)}) is outside opening hours "
                        f"{_fmt(h.opens)}-{_fmt(h.closes)}",
                    ),
                    item_ids=[v.item_id],
                    day=day_no,
                )
            )
    return out


# --- iron rule 4: visit <-> transfer connection buffer --------------------


def _check_transfer_buffer(
    day_no: int, visits: list[VisitItem], transfers: list[TransferItem]
) -> list[RuleViolation]:
    buf = INTERCITY_BUFFER_MINUTES
    out = []
    for tr in transfers:
        if tr.start_time is None:
            continue
        tr_start = _minutes(tr.start_time)
        tr_end = _eff_end_minutes(tr)
        tr_end_window = tr_end if tr_end is not None else tr_start
        for v in visits:
            if v.start_time is None or v.end_time is None:
                # Untimed visits are invisible to every downstream check, so
                # a "day 3 in Xiamen + 9am flight" layout ships silently.
                # Hard-fail it: the caller must time or relocate the visit.
                out.append(
                    RuleViolation(
                        rule_id=4,
                        severity=RuleSeverity.error,
                        message=L(
                            f"第{day_no}天 跨城交通 {tr.from_city}→{tr.to_city}"
                            f" 当天的景点「{v.name}」没有起止时间，无法校验衔接，"
                            "请安排时间或移动到其他天",
                            f'Day {day_no}: sight "{v.name}" on the day of the '
                            f"intercity transfer {tr.from_city}→{tr.to_city} has no "
                            "start/end time, so the connection cannot be checked. "
                            "Schedule a time or move it to another day",
                        ),
                        item_ids=[v.item_id],
                        day=day_no,
                    )
                )
                continue
            vs, ve = _minutes(v.start_time), _minutes(v.end_time)
            if vs < tr_end_window + buf and ve > tr_start - buf:
                out.append(
                    RuleViolation(
                        rule_id=4,
                        severity=RuleSeverity.error,
                        message=L(
                            f"第{day_no}天 {v.name} 与跨城交通"
                            f"{tr.from_city}→{tr.to_city}"
                            f"({_fmt(tr.start_time)}-{_fmt(tr.end_time)})"
                            f"衔接缓冲不足 {buf} 分钟",
                            f"Day {day_no}: {v.name} and intercity transfer "
                            f"{tr.from_city}→{tr.to_city}"
                            f"({_fmt(tr.start_time)}-{_fmt(tr.end_time)}) have "
                            f"less than {buf} minutes of connection buffer",
                        ),
                        item_ids=[v.item_id, tr.item_id],
                        day=day_no,
                    )
                )
    return out


# --- iron rule 5: same-day multi-transfer seq order + mutual buffer -------


def _check_transfer_sequence(
    day_no: int, transfers: list[TransferItem]
) -> list[RuleViolation]:
    out = []
    if len(transfers) < 2:
        return out
    seqs = [t.seq for t in transfers]
    if len(set(seqs)) != len(seqs):
        out.append(
            RuleViolation(
                rule_id=5,
                severity=RuleSeverity.error,
                message=L(
                    f"第{day_no}天 多段跨城交通 seq 必须递增且唯一，实际为 {seqs}",
                    f"Day {day_no}: multiple same-day intercity transfers must "
                    f"have strictly increasing unique seq, got {seqs}",
                ),
                item_ids=[t.item_id for t in transfers],
                day=day_no,
            )
        )
    ordered = sorted(transfers, key=lambda t: t.seq)
    for prev, cur in zip(ordered, ordered[1:]):
        prev_end = _eff_end_minutes(prev)
        cur_start = _minutes(cur.start_time) if cur.start_time is not None else None
        if prev_end is None or cur_start is None:
            continue
        gap = cur_start - prev_end
        if gap < INTERCITY_BUFFER_MINUTES:
            out.append(
                RuleViolation(
                    rule_id=5,
                    severity=RuleSeverity.error,
                    message=L(
                        f"第{day_no}天 跨城交通 {prev.from_city}→{prev.to_city} 与 "
                        f"{cur.from_city}→{cur.to_city} 衔接缓冲 {gap} 分钟 < "
                        f"{INTERCITY_BUFFER_MINUTES} 分钟（含时间重叠 / seq 顺序颠倒）",
                        f"Day {day_no}: intercity transfers {prev.from_city}→"
                        f"{prev.to_city} and {cur.from_city}→{cur.to_city} "
                        f"connection buffer {gap} min < {INTERCITY_BUFFER_MINUTES} "
                        "min (includes time overlap / seq out of order)",
                    ),
                    item_ids=[prev.item_id, cur.item_id],
                    day=day_no,
                )
            )
    return out


# --- iron rule 6: pace (walk distance + effective tour ratio) -------------


def _check_pace(
    day_no: int,
    day_items: list[VisitItem | TransferItem],
    visits: list[VisitItem],
    crowd_profile: CrowdProfile,
) -> list[RuleViolation]:
    out = []
    # walking distance: adjacent same-day visits, straight-line (haversine)
    # approximation; segments touching a location-less item are skipped.
    km = sum(
        haversine_km(a.location, b.location)
        for a, b in zip(visits, visits[1:])
        if a.location is not None and b.location is not None
    )
    located = [v for v in visits if v.location is not None]
    limit = WALK_KM_PER_DAY_MAX * CROWD_COEFFICIENTS[crowd_profile]
    if located and km > limit:
        out.append(
            RuleViolation(
                rule_id=6,
                severity=RuleSeverity.warning,
                message=L(
                    f"第{day_no}天 步行距离约 {km:.1f} km（直线距离近似）超过 "
                    f"{limit:.1f} km 上限（{crowd_profile.value} 人群系数）",
                    f"Day {day_no}: estimated walking distance ~{km:.1f} km "
                    f"(straight-line approximation) exceeds the {limit:.1f} km "
                    f"limit ({crowd_profile.value} crowd coefficient)",
                ),
                item_ids=[v.item_id for v in located],
                day=day_no,
            )
        )
    # effective sightseeing ratio: Σ visit duration / day time span.
    timed = [
        i
        for i in day_items
        if i.start_time is not None and _eff_end_minutes(i) is not None
    ]
    if timed:
        span = max(_eff_end_minutes(i) for i in timed) - min(
            _minutes(i.start_time) for i in timed
        )
        total = sum(v.duration_minutes for v in visits if v.duration_minutes)
        if span > 0 and total > 0 and total / span < VALID_TOUR_RATIO_MIN:
            out.append(
                RuleViolation(
                    rule_id=6,
                    severity=RuleSeverity.warning,
                    message=L(
                        f"第{day_no}天 有效游览时长占比 {total / span:.0%} 低于 "
                        f"{VALID_TOUR_RATIO_MIN:.0%}",
                        f"Day {day_no}: effective sightseeing ratio "
                        f"{total / span:.0%} is below {VALID_TOUR_RATIO_MIN:.0%}",
                    ),
                    item_ids=[
                        v.item_id for v in visits if v.duration_minutes is not None
                    ],
                    day=day_no,
                )
            )
    return out


# --- iron rule 3 (simplified): geography sanity ---------------------------


def _check_visit_cities(
    plan: ItineraryPlan, day: DayPlan, visits: list[VisitItem]
) -> list[RuleViolation]:
    out = []
    plan_cities = {_norm_city(c) for c in plan.cities}
    for v in visits:
        if _norm_city(v.city) not in plan_cities:
            out.append(
                RuleViolation(
                    rule_id=3,
                    severity=RuleSeverity.warning,
                    message=L(
                        f"第{day.day}天 {v.name} 所在城市 {v.city} "
                        f"不在行程城市 {plan.cities} 中",
                        f"Day {day.day}: {v.name} is in city {v.city}, which is "
                        f"not among the itinerary cities {plan.cities}",
                    ),
                    item_ids=[v.item_id],
                    day=day.day,
                )
            )
    return out


def _check_base_city_jumps(plan: ItineraryPlan) -> list[RuleViolation]:
    out = []
    for prev, cur in zip(plan.days, plan.days[1:]):
        # 跨城交通可以在 base 切换的前一天（出发日）或当天（到达日）——
        # 只看"变化当日"会把前一天已乘车的正常行程误报为跳变。
        jumped = _norm_city(cur.base_city) != _norm_city(prev.base_city)
        has_transfer = any(isinstance(i, TransferItem) for i in prev.items) or any(
            isinstance(i, TransferItem) for i in cur.items
        )
        if jumped and not has_transfer:
            out.append(
                RuleViolation(
                    rule_id=3,
                    severity=RuleSeverity.warning,
                    message=L(
                        f"第{cur.day}天 基准城市从 {prev.base_city} 跳变到 "
                        f"{cur.base_city} 但当日无跨城交通",
                        f"Day {cur.day}: base city jumps from {prev.base_city} to "
                        f"{cur.base_city} with no intercity transfer that day",
                    ),
                    day=cur.day,
                )
            )
    return out


# --- public API -----------------------------------------------------------


def _check_delivery_gates(
    day_no: int,
    visits: list[VisitItem],
    hours: dict,
) -> list[RuleViolation]:
    """交付闸（2026-11-04 it-b986c4f6 熊猫基地挂日尾事故后收口）：

    ① 钉住条目未排入时刻=error——必去/用户钉的点以「无时刻」交付是
       优先级倒挂（凑数点霸下午、必去挂日尾渲染成四点以后）；
    ② 同日下午（≥13:00 开场）大点 ≥2=warning（下午单大点，2026-11-04
       拍板「超过 80 分钟的下午就放一个」）；
    ③ 白天入场开场闸超限=warning（2026-11-07 用户再拍板：观光须 16:00
       前安排（开场），时长可跨界收尾；大点 15:30 开场带并列上限；夜游/
       演出/餐/酒店/用户钉住有时刻豁免面与 solver generic_entry_cap
       完全同口径）——仅在营业窗已知（poi_id 命中 hours）时判，避免
       poi_hours=[] 的结构校验调用对夜开场馆误报。

    solver 路径的罚分/闸不覆盖 LLM 改写、H5 move 等旁路，这里是独立
    的读侧最后一道网。"""
    out: list[RuleViolation] = []
    afternoon_bigs = 0
    for v in visits:
        if v.pinned and v.start_time is None:
            out.append(
                RuleViolation(
                    rule_id=19,
                    severity=RuleSeverity.error,
                    message=L(
                        f"第{day_no}天 必去/钉住条目「{v.name}」未排入时刻",
                        f'Day {day_no}: pinned must-visit "{v.name}" has no time slot',
                    ),
                    item_ids=[v.item_id],
                    day=day_no,
                )
            )
        if v.start_time is None:
            continue
        start = _minutes(v.start_time)
        if start >= AFTERNOON_START_MINUTES and _is_big_site(v):
            afternoon_bigs += 1
        window = hours.get(v.poi_id)
        cap = (
            generic_entry_cap(v, window)
            if (v.category or "") not in ("food", "hotel") and window is not None
            else None
        )
        if cap is not None and start > cap:
            out.append(
                RuleViolation(
                    rule_id=7,
                    severity=RuleSeverity.warning,
                    message=L(
                        f"第{day_no}天 「{v.name}」{v.start_time.strftime('%H:%M')}"
                        " 开场——白天观光须 16:00 前安排（大点最晚 15:30 开场）",
                        f'Day {day_no}: "{v.name}" starts '
                        f"{v.start_time.strftime('%H:%M')} — daytime sights "
                        "must be scheduled by 16:00 (big sites by 15:30)",
                    ),
                    item_ids=[v.item_id],
                    day=day_no,
                )
            )
    if afternoon_bigs > 1:
        names = "、".join(
            v.name
            for v in visits
            if v.start_time is not None
            and _minutes(v.start_time) >= AFTERNOON_START_MINUTES
            and _is_big_site(v)
        )
        out.append(
            RuleViolation(
                rule_id=7,
                severity=RuleSeverity.warning,
                message=L(
                    f"第{day_no}天 下午排了 {afternoon_bigs} 个大点"
                    f"（{names}）——一般下午只放一个大点",
                    f"Day {day_no} afternoon has {afternoon_bigs} big sights "
                    f"({names}) — usually one per afternoon",
                ),
                day=day_no,
            )
        )
    return out


def validate_plan(
    plan: ItineraryPlan,
    *,
    poi_hours: list[PoiHours],
    crowd_profile: CrowdProfile = CrowdProfile.normal,
) -> ValidationReport:
    """Validate iron rules 1/2/3/4/5/6 over a whole plan (pure function)."""
    hours = {h.poi_id: h for h in poi_hours}
    violations: list[RuleViolation] = []
    for day in plan.days:
        visits = [i for i in day.items if isinstance(i, VisitItem)]
        transfers = [i for i in day.items if isinstance(i, TransferItem)]
        violations += _check_time_conflicts(day.day, visits)
        violations += travel_gap_violations(day.day, visits)
        violations += _check_opening_hours(day.day, visits, hours)
        violations += _check_transfer_buffer(day.day, visits, transfers)
        violations += _check_transfer_sequence(day.day, transfers)
        violations += _check_pace(day.day, day.items, visits, crowd_profile)
        violations += _check_visit_cities(plan, day, visits)
        violations += _check_delivery_gates(day.day, visits, hours)
    violations += _check_base_city_jumps(plan)
    return _report(violations)


# 腿标注的展示字段全集（annotate_legs 出口端恒补）：2026-11-16 补
# next_leg_minutes/mode/cost_cny——2026-11-13 加腿模式与费用后 model_copy
# 只归一三键，纯展示漂移又被判成「早于 from_day 却变了」（铁律 10 误报）
_SCOPE_IGNORE_FIELDS = (
    "distance_to_next_km",
    "next_walk_minutes",
    "leg_source",
    "next_leg_minutes",
    "next_leg_mode",
    "next_leg_cost_cny",
)


def _scope_key(day: DayPlan):
    """铁律 10 的语义比较键：腿标注字段（legs.annotate_legs 出口端恒补的
    展示字段）归一化后比——旧计划从存储进来无标注，新计划经 mutate 出口
    必带标注，整对象相等比较会把纯展示漂移误报成越界（2026-11-10 GAP-4）。"""
    return (
        day.base_city,
        tuple(
            i.model_copy(update={f: None for f in _SCOPE_IGNORE_FIELDS})
            for i in day.items
        ),
    )


def validate_change_scope(
    old_plan: ItineraryPlan, new_plan: ItineraryPlan, *, from_day: int
) -> ValidationReport:
    """Iron rule 10: days strictly before from_day must be untouched."""
    old_days = {d.day: d for d in old_plan.days}
    new_days = {d.day: d for d in new_plan.days}
    violations = []
    for day_no in sorted(old_days):
        if day_no >= from_day:
            continue
        old_d = old_days[day_no]
        new_d = new_days.get(day_no)
        if new_d is None or _scope_key(new_d) != _scope_key(old_d):
            violations.append(
                RuleViolation(
                    rule_id=10,
                    severity=RuleSeverity.error,
                    message=L(
                        f"第{day_no}天 早于 from_day={from_day} 却与原计划不一致"
                        "（铁律 10：只动当天及之后）",
                        f"Day {day_no} is before from_day={from_day} but differs "
                        "from the original plan (iron rule 10: only change the "
                        "current day onward)",
                    ),
                    item_ids=[i.item_id for i in old_d.items],
                    day=day_no,
                )
            )
    return _report(violations)


def validate_pinned(
    old_plan: ItineraryPlan, new_plan: ItineraryPlan
) -> ValidationReport:
    """Iron rule 19: pinned VisitItems must survive unmoved and unretimed."""
    new_by_id = {i.item_id: i for d in new_plan.days for i in d.items}
    violations = []
    for d in old_plan.days:
        for old in d.items:
            if not (isinstance(old, VisitItem) and old.pinned):
                continue
            new = new_by_id.get(old.item_id)
            if new is None:
                violations.append(
                    RuleViolation(
                        rule_id=19,
                        severity=RuleSeverity.error,
                        message=L(
                            f"第{d.day}天 {old.name} 已被用户确认（pinned）却被删除",
                            f"Day {d.day}: {old.name} was user-confirmed (pinned) "
                            "but got deleted",
                        ),
                        item_ids=[old.item_id],
                        day=d.day,
                    )
                )
            elif (
                new.day != old.day
                or new.start_time != old.start_time
                or new.end_time != old.end_time
            ):
                violations.append(
                    RuleViolation(
                        rule_id=19,
                        severity=RuleSeverity.error,
                        message=L(
                            f"第{d.day}天 {old.name} 已被用户确认（pinned）"
                            "却被移动或改时间",
                            f"Day {d.day}: {old.name} was user-confirmed (pinned) "
                            "but got moved or retimed",
                        ),
                        item_ids=[old.item_id],
                        day=d.day,
                    )
                )
    return _report(violations)
