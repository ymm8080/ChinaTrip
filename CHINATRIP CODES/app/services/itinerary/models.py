"""Itinerary domain schema (design v2.0 §4/§6.0/§6.4).

Shared vocabulary for the mutation pipeline (iron rules 0-23), the CP-SAT
solver (§6.9), the planning agent (§6.1-6.3) and restaurant insertion
(§6.2 v1.7). Pure pydantic — no DB, no LLM, no I/O.
"""

from datetime import time
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

# --- pace / buffer constants (iron rule 6 quantified, §6.4) ---

WALK_KM_PER_DAY_MAX = 15.0  # x crowd coefficient 0.6-1.2
CROWD_COEF_MIN = 0.6
CROWD_COEF_MAX = 1.2
VALID_TOUR_RATIO_MIN = 0.55  # effective sightseeing time ratio >= 55%
INTERCITY_BUFFER_MINUTES = 90  # iron rule 4: cross-city connection buffer

# 落地首停规则（2026-11-01 用户拍板「行程里应该有 HOTEL」）：火车/飞机
# 落地后默认先到酒店——入住卡摆在落地 +90 分钟（铁律 4 衔接缓冲=出站+
# 去酒店，即「到达酒店」的默认估计），到店 1 小时后出发去当天首个行程；
# 无酒店卡（用户删除/深夜放不下）时首个观光同样 ≥ 落地 +150（2.5h）。
# solver CP/插入两条主路与 plan 兜底三处同口径。
ARRIVAL_STOP_FLOOR_MINUTES = 150  # landing -> first attraction floor
HOTEL_SETTLE_MINUTES = 60  # hotel arrival -> depart to next attraction


class GeoPoint(BaseModel):
    lon: float
    lat: float


class VisitItem(BaseModel):
    """A POI visit inside one day (food items reuse this, category=food)."""

    item_id: str
    name: str
    poi_id: str | None = None
    category: str | None = None  # sight|food|...
    city: str
    location: GeoPoint | None = None
    # Concrete address + opening hours shown with every recommendation
    # (product rule 2026-10-19); None when amap data is unavailable.
    address: str | None = None
    opening_hours: str | None = None
    # 双语 P1（DESIGN language_dual_system §6）：_en 并出，空回退中文，
    # H5 按 locale 取值；来源候选库 pois._en 列，amap 路径为 None
    name_en: str | None = None
    address_en: str | None = None
    intro_en: str | None = None
    opening_hours_en: str | None = None
    day: int  # 1-based day number
    start_time: time | None = None
    end_time: time | None = None
    duration_minutes: int | None = None
    # Display-only leg to the next stop of the same day (v2.4.3 §5
    # 行程时间轴, product rule 2026-10-19): straight-line distance + walk
    # estimate, computed by itinerary.legs.annotate_legs after every plan
    # mutation; never user input.
    distance_to_next_km: float | None = None
    next_walk_minutes: int | None = None
    leg_source: Literal["estimate", "amap", "baidu"] | None = None
    # Iron rule 19: user-confirmed items must not be moved by solver/LLM.
    pinned: bool = False
    # 系统钉（2026-10-31 午餐软钉拍板；2026-11-01 晚扩展「午饭/顺路
    # 餐厅/晚饭不钉死」）：排程器自己摆的餐件标记——pinned 可为 False
    # （非铁律 19：用户可拖/可改时/LLM 可挪），solver 仍以落位时刻为
    # 软锚（普通日零漂移，弹性日 ±30/午餐可缩）；用户手钉（retime/
    # move/pin 端点）恒 False，铁律 19 不受软钉影响。
    soft_pin: bool = False
    # 0009 / 8.2.1：库候选携带的时段属性（morning/afternoon/evening/
    # sunset/sunrise/any），solver 据此收窄开窗（夜景自动排晚上）；
    # None = 无信号（老数据/占位），按全天窗处理。
    best_visit_time: str | None = None
    # 路径 A 预填（show_booking_design §2，2026-10-26）：库行 booking_url
    # （演出=携程 sight SKU 页）并出——H5 票务直达直开成品页，跳过搜索；
    # None=无库链接，H5 走 order-intent 的 geo 模板兜底。
    booking_url: str | None = None
    # G1（§14.3）：预约制门票提示（展示层，solver 不约束——预约是用户
    # 侧动作；「现在就订·提前 N 天·放票 08:00」在卡片亮出）
    reservation_hint: str | None = None
    # 8.1.4 天气感知（§14）：库候选的露天/室内属性透传（yes=雨宜/no=露天），
    # H5 与 forecast 对照生成「雨天对调」横幅；None=无信号不提示
    rain_ok: str | None = None
    # 候选源档（_source_tier 1=UNESCO..11=other，2026-11-03 名录序，
    # plan.py 装配期透传）：边日轻重拍板（2026-11-03「重要景点不放在
    # 到达/离开日」）靠它认重磅（≤4）与轻 CityWalk（8=街区）；
    # None=占位/老数据按中档处理。
    tier: int | None = None
    # 同级备选（2026-11-05 拍板「每个点要有一个备选」）：展示层字段——
    # api/plan._plan_turn_body 装配期在深拷贝上挂（session.plan 本体永不
    # 携带，持久化不留展示数据）；规则见 app.services.poi_alternatives
    # （同级·同类·同时长·同城·排除行程内已有）。None = 未装配/无候选。
    alternatives: list["PlanAlternative"] | None = None


class PlanAlternative(BaseModel):
    """行程卡右侧「同级备选」chip 的载荷（2026-11-05 拍板）。

    规则（poi_alternatives.pick_alternatives 唯一定义点）：与主点同层级
    （tier 档号一致，档 4 短视频/5 小红书并作社媒档）、同类别（受控类别
    精确匹配，空缺时类别组放宽）、游时时长相近（band 内）、同城可选、
    排除行程内已有站点。H5 点击 chip → /items/{id}/replace 原位换主点。
    """

    name: str
    name_en: str | None = None
    category: str | None = None
    # 名录档号（hit_tier 口径 0=unesco..9=3a，10=未分层）——H5 据此亮
    # 同级徽标；与主点同档是本功能的硬规则。
    tier: int | None = None
    # 层级短牌（unesco/5a/ta/intl/social/…，poi_details._TIER_TAG 口径）
    level_tag: str | None = None
    duration_minutes: int | None = None
    # 与主点直线距离（km，annotate 同式 haversine）：同档同城内近者优先
    distance_km: float | None = None
    rating: float | None = None


class TransferItem(BaseModel):
    """An intercity transfer segment (iron rule 5: seq-ordered, buffered)."""

    item_id: str
    day: int
    seq: int  # order among that day's transfers
    from_city: str
    to_city: str
    mode: Literal["train", "flight", "car", "bus"] = "train"
    start_time: time | None = None
    end_time: time | None = None
    duration_minutes: int | None = None
    train_no: str | None = None  # TrainService static-lib hit, if any
    flight_no: str | None = None  # FlightService hit (outbound/return legs)


class DayPlan(BaseModel):
    day: int
    base_city: str  # city the user wakes up in
    items: list[VisitItem | TransferItem] = Field(default_factory=list)


class ItineraryPlan(BaseModel):
    """Working copy of an itinerary (snapshots freeze this, iron rule 16)."""

    itinerary_id: str
    cities: list[str]
    days: list[DayPlan]
    assumptions: list[str] = Field(default_factory=list)
    # 出发日期（ISO "YYYY-MM-DD"）——每日日期 = start_date + (day-1)，随快照
    # 持久化；行程卡日期与天气都以此为基准。None = 未设出发日期。
    start_date: str | None = None


class PoiHours(BaseModel):
    """Opening-hours rule used by iron rule 2 (validation input).

    G3（§14.3）：多段开窗（国内场馆午休闭馆 12:00-13:30 常态）——
    windows 非空时 opens/closes 仅为兜底显示值，solver 按 windows
    条件开窗建模。
    """

    poi_id: str
    opens: time
    closes: time
    windows: list[tuple[time, time]] | None = None


class RuleSeverity(str, Enum):
    error = "error"  # hard: plan is invalid, must be repaired
    warning = "warning"  # soft: surfaced to the user


class RuleViolation(BaseModel):
    rule_id: int  # iron rule number 0-23
    severity: RuleSeverity
    message: str
    item_ids: list[str] = Field(default_factory=list)
    day: int | None = None


class ValidationReport(BaseModel):
    ok: bool  # no error-severity violations
    violations: list[RuleViolation] = Field(default_factory=list)


class DiffOp(BaseModel):
    """Unified change op (iron rule 0): LLM rerank / manual drag / snapshot
    restore / solver output all speak this."""

    op: Literal["add", "remove", "move", "retime"]
    item_id: str | None = None
    item: VisitItem | TransferItem | None = None  # for add
    new_day: int | None = None  # for move
    new_start_time: time | None = None  # for retime/move


class ChangeSummary(BaseModel):
    """Iron rule 19: minimal-change principle output."""

    change_summary: list[str] = Field(default_factory=list)
    affected_items_count: int = 0
    reasoning: str | None = None


class CrowdProfile(str, Enum):
    """Crowd coefficient band for the pace rule (iron rule 6)."""

    slow = "slow"  # 0.6 - families with kids / elderly
    normal = "normal"  # 1.0
    fast = "fast"  # 1.2 - solo / sporty
