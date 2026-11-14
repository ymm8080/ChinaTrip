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
# 落地/离城缓冲（2026-11-14 用户拍板）：飞机 3 小时、火车 2 小时。
# 落地侧＝到达时刻 + 缓冲才算「人已在城里」；离城侧＝最后一件必须在
# 出发时刻 − 缓冲之前收尾（值机安检/进站排队都算在里面）。
ARRIVAL_BUFFER_FLIGHT_MINUTES = 180
ARRIVAL_BUFFER_TRAIN_MINUTES = 120


def arrival_buffer_minutes(mode: str | None) -> int:
    """落地侧缓冲：飞机 180 / 火车 120 / 其它沿用铁律 4 的 90。"""
    mode = (mode or "").strip().lower()
    if mode == "flight":
        return ARRIVAL_BUFFER_FLIGHT_MINUTES
    if mode == "train":
        return ARRIVAL_BUFFER_TRAIN_MINUTES
    return INTERCITY_BUFFER_MINUTES


def arrival_floor_minutes(mode: str | None) -> int:
    """落地 → 当天首个景点地板：飞机 3 小时 / 火车 2 小时。

    3 小时/2 小时已经把「入境/取行李 + 进城 + 到店放包」算在里面，不再
    额外加 60 分钟休整（用户 2026-11-14 口径）。
    """
    return arrival_buffer_minutes(mode)


def departure_buffer_minutes(mode: str | None) -> int:
    """离城侧缓冲：飞机 3 小时（值机+安检）、火车 2 小时（进站）。"""
    return arrival_buffer_minutes(mode)
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
    # 餐卡贴前一站落位（2026-11-13 用户指令「BLANK LUNCH CARD 默认取上一站
    # 地址」）：午饭/晚饭占位件本身没有 POI，卡面地址与「距下一站」展示腿
    # 都从当天前一落脚点继承。anchor_location 只服务展示腿与卡片地址——
    # location 保持 None：solver 动线矩阵、铁律 7 间隔、回填/小时链口径不变。
    anchor_from_prev: bool = False
    anchor_location: GeoPoint | None = None
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
    # 必去/心愿卡（plan._merge_must_visits 装配期落标）：铁律 19 的去重
    # 侧保护——同站孪生合并时必去卡永不让位（2026-11-07 锦里古戏台/
    # 武侯祠案：两张愿望全被一张「武侯祠·锦里」复合挂牌池卡冒充吸收，
    # 卡被去重并掉后必去静默蒸发）。solves 前装配即打，与 solve 后的
    # pinned 钉位（:7946 一带）互不干扰。
    must: bool = False
    # 手建卡（2026-11-08 拍板乙·三级梯 心愿>CREATED>TAG）：选层候选
    # _created_lane 装配期透传（plan.py 池绑定 :9408 一带打标）。梯级
    # 高于 TAG——终删层（楔子清障 _evict_wedge_strays 等）永不下杀手：
    # 楔入态改强制归位（踢 kin 多数日最弱 TAG 让位）或原地保留带披露。
    created: bool = False
    # 精选库卡（2026-11-08 拍板「我说的是 CURATED，不是 CREATED flag」）：
    # 池侧 curated 行（source='curated'，如长安十二时辰·唐宴；36 城宴会
    # 普查/intl 精选种子）装配期透传（plan.py _cand_is_curated）。与
    # created 同待遇——永不进删除闸；宴秀卡（curated+food）的取消/让位
    # 仍按簇跟随者规则（已定稿），不受本字段豁免。
    curated: bool = False
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
    # 升旗时刻锚（flag_schedule 设计 2026-11-14）：装配期按官方升降旗表
    # 打标的精确开始时刻（仅天安门广场；plan._apply_flag_schedule 落标）。
    # solver 两路（CP/最廉插入）都把它当完全钉死项：start 恰落该点，且可
    # 破 DAY_START 日始下界（升旗 4:45-7:36 早于 8:30 日始）。展示层不读
    # 此字段；用户自钉（pinned 且非 soft_pin）时铁律 19 优先，锚跳过。
    fixed_sessions: list[time] | None = None
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
    # 名录秩（2026-11-13 三拍定序「时长久不是优先因子」）：0=UNESCO 世界遗产
    # 本体、10=curated/国际站精选、20=unesco_* 串号子项、30=5A 本体、40=其它；
    # None=未分层。族日择日、让位弹座按本秩排，tier 只作同秩内次序。
    site_rank: int | None = None
    # 同级备选（2026-11-05 拍板「每个点要有一个备选」）：展示层字段——
    # api/plan._plan_turn_body 装配期在深拷贝上挂（session.plan 本体永不
    # 携带，持久化不留展示数据）；规则见 app.services.poi_alternatives
    # （同级·同类·同时长·同城·排除行程内已有）。None = 未装配/无候选。
    alternatives: list["PlanAlternative"] | None = None
    # 同街族并卡（2026-11-07 拍板「同街族合成一卡，时长取最大」）：
    # 与主点直线 ≤1km 的同日站点折进主卡 chips，只出不排（solver/兜底
    # 只见主卡，族窗口=最长一站）；None=独立卡（>1km 保持多卡）。
    stops: list["PlanStop"] | None = None


class PlanStop(BaseModel):
    """同街族并卡里被主卡吸收的子站 chip（2026-11-07 拍板）。

    只携带卡面展示字段，不参与排程（主卡时长已取族内最大）。name 按
    主卡同款双语口径并出 _en；poi_id 供心愿覆盖核对（_sync_wish_rows /
    _ensure_wishlist_coverage 都会扫子站名/号）。
    """

    name: str
    name_en: str | None = None
    poi_id: str | None = None
    category: str | None = None
    duration_minutes: int | None = None


class UnplacedCandidate(BaseModel):
    """「想排没排进去」候选的结构化留痕（2026-11-11 用户拍板「可替代品不
    一定同品类，也可以是想排没有排进去的景点放在右边」）。

    规划器在必去让位/弃排点记录（机器可读，区别于 assumptions 自由文
    本）；attach_plan_alternatives 装配期把条目转成宿主卡右侧 chip（跨
    品类放行，点亮「想去」徽标），点击走同一换点端点。
    """

    name: str
    name_en: str | None = None
    poi_id: str | None = None
    category: str | None = None
    # 选点梯子档号（plan 口径 1..11），chip 亮牌/排序用
    tier: int | None = None
    duration_minutes: int | None = None
    location: GeoPoint | None = None
    city: str | None = None
    # 本想排入的天号（选宿主卡首选键：同天优先）
    day_hint: int | None = None
    # yield_must=必去让位被挤 / yield_rain=雨天软规则落选 / cap=日容量弃排
    reason: str | None = None


class PlanAlternative(BaseModel):
    """行程卡右侧「同级备选」chip 的载荷（2026-11-05 拍板）。

    规则（poi_alternatives.pick_alternatives 唯一定义点）：与主点同层级
    （tier 档号一致，档 4 短视频/5 小红书并作社媒档）、同类别（受控类别
    精确匹配，空缺时类别组放宽）、游时时长相近（band 内）、同城可选、
    排除行程内已有站点。H5 点击 chip → /items/{id}/replace 原位换主点。
    「想排未排」chip（2026-11-11 拍板跨品类）不受同级/同类硬闸约束，
    level_tag="want" 亮「想去」徽标。
    """

    name: str
    name_en: str | None = None
    category: str | None = None
    # 名录档号（hit_tier 口径 0=国际站 1=unesco 2=5a..9=3a，10=未分层）
    # ——H5 据此亮同级徽标；与主点同档是本功能的硬规则。
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
    # 想排未排入候选（2026-11-11 拍板「可替代品跨品类」）：必去让位/弃排点
    # 结构化留痕，装配期作 chip 挂上相关卡右侧；assumptions 自由文本之外
    # 的机器可读池。
    unplaced: list[UnplacedCandidate] = Field(default_factory=list)
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
