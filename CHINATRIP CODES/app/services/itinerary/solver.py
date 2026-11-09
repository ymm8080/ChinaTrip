"""CP-SAT itinerary solver (design v2.0 §6.9).

Division of labour: the LLM owns understanding and POI selection; this
module owns feasibility and optimality of the schedule. Each visit is an
interval variable in the optional domain 08:00-21:00 with hard
constraints (opening-hour windows, no-overlap, intercity buffers around
fixed transfers, iron rule 19 pins) and a soft objective: minimise total
adjacent-pair travel when a matrix is supplied, else minimise makespan.

Degradation contract (§6.9): ``None`` = infeasible or no solution within
the time budget -> the caller falls back to the LLM self-repair chain
(<= 3 rounds). No partial day is ever returned.
"""

from __future__ import annotations

import logging
import math
import os
import re
from datetime import time
from typing import NamedTuple

from ortools.sat.python import cp_model

from app.services.itinerary.models import (
    ARRIVAL_STOP_FLOOR_MINUTES,
    INTERCITY_BUFFER_MINUTES,
    DayPlan,
    GeoPoint,
    ItineraryPlan,
    PoiHours,
    TransferItem,
    VisitItem,
)
from app.services.restaurants import (
    LUNCH_DURATION_FLOOR_MINUTES,
    LUNCH_START_EARLIEST,
    LUNCH_START_LATEST,
    is_dinner_placeholder,
    is_lunch_placeholder,
)

logger = logging.getLogger(__name__)

#: Visits may be placed anywhere in [09:00, 21:00] (minutes since midnight).
# 2026-10-31 拍板：景点活动一天 9 点开始（8 点太早）；交通除外——
# 车次/航班时刻是客观固定窗，不受此日始钳制（火车 8 点出发照常）。
DAY_START_MINUTES = 9 * 60
DAY_END_MINUTES = 21 * 60
#: Fallback when an item carries no duration.
DEFAULT_VISIT_MINUTES = 60
#: Fallback when the travel matrix has no entry for an ordered pair.
DEFAULT_TRAVEL_MINUTES = 30
# 0009 / 8.2.1：best_visit_time 枚举 → 时段窗（分钟，[起, 止)）。表内不收
# "any"：字段为 None/"any"/未知脏值时查表落空，按全天窗处理不约束。
_BEST_VISIT_WINDOWS: dict[str, tuple[int, int]] = {
    "morning": (9 * 60, 12 * 60),  # 09:00-12:00（随日始 9 点，2026-10-31）
    "afternoon": (12 * 60, 17 * 60),  # 12:00-17:00
    "evening": (17 * 60, 21 * 60),  # 17:00-21:00（夜景自动排晚上）
    "sunset": (16 * 60, 19 * 60),  # 16:00-19:00 近似窗
    "sunrise": (9 * 60, 10 * 60 + 30),  # 09:00-10:30 近似窗（随日始）
}

#: 2026-11-06 拍板：无场次演出不再默认晚场（旧 S5 §4 曾把无场次演出
#: 钉死 20:10-20:45 开演域，全天滚动型街区被硬套固定晚场默认）——
#: 无场次演出按正常景点逻辑排（营业窗 + best_visit 晚场豁免闸不约束），
#: 带真场次（约xx:xx 串）的演出仍走场次点窗通道。


def _is_show(item: VisitItem) -> bool:
    return item.best_visit_time == "show" or item.category == "entertainment"


#: 演出场次串「多场（约15:00/20:00，旺季加场至4场）」「傍晚/晚间场（约
#: 17:30/19:30两场）」——场次列表是真值源（23552b5 show_sessions 刷新
#: 管线写入 opening_hours 列）。
_SESSION_LIST_RE = re.compile(r"约\s*((?:\d{1,2}:\d{2}\s*[/、,]\s*)+\d{1,2}:\d{2})")
_SESSION_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")


def show_session_starts(text: str | None) -> list[int]:
    """opening_hours 场次串 → 当日场次起点分钟表（升序去重）；解析不出回空。

    2026-10-31 上午空排事故根因之一：S5 把一切演出钉死 20:10-20:45
    晚场，白天多场演出（如《复活的军团》约11:10/12:00/13:40/16:20/
    17:10）同日多场被硬塞同一个 35 分钟晚窗 → 单日不可行 → 整单降级。
    场次表存在时 solver 应按真场次开窗（_visit_spec 场次点窗通道）。
    """
    if not text:
        return []
    starts: list[int] = []
    for m in _SESSION_LIST_RE.finditer(text):
        for hh, mm in _SESSION_TIME_RE.findall(m.group(1)):
            t = int(hh) * 60 + int(mm)
            if DAY_START_MINUTES <= t <= DAY_END_MINUTES:
                starts.append(t)
    return sorted(set(starts))


#: 2026-10-31 用户拍板（城心簇古迹 17:00 入场事故）→ 2026-11-01 修正
#: （远郊大点 18:00 排期事故）→ 2026-11-03 再裁定（第1天城心大点
#: 18:43 排期事故）→ 2026-11-05 曾升级为「结束闸」（开场+时长≤16:30）
#: → **2026-11-07 用户再拍板（第5次重述）**：「观光须 16:00 前安排」
#: ——回归**开场闸**且收紧到 16:00：观光须 16:00 前开场，时长可以
#: 自然跨过 16:00，营业窗 + 日终 21:30 照卡（结束闸把 240min 级大块
#: 头压成「必须上午整块开场」，大型综合体类下午档结构性无解，故废）。
#: 转场/到达日一律适用——装不下就挪日，不在傍晚硬排。豁免：用户自
#: 钉且有时刻（铁律 19）、夜间属性点（best_visit_time=evening/
#: sunset/show）、仅晚间开放的场馆（全窗开 ≥17:00=夜游类）、餐饮/
#: 酒店/交通/演出类条目。大点另有 15:30 开场带（并列上限）。
_GENERIC_ENTRY_CAP_MINUTES = 16 * 60

# 大点三口径（2026-11-04 用户拍板「大型的旅游景区不适合放下午16:00。
# 超过80分钟的一般下午就放一个。然后搭配一个近距离的CITYWALK。当天
# 应该先排大点，再排轻点」）：「大点」=时长>80min、非街区
# （tier8=街区轻 CityWalk 不算大——它正是大点后面配的近游）的非餐/
# 酒店/演出观光点（夜属性/用户自钉有时刻豁免，同入场闸豁免面）。
# ① 开场闸加严：大点最晚 15:30 开场（16:00 起排的大点天黑前走不完；
#    普通点维持 16:30；晚开门豁免按各自闸值判）；
# ② 下午单大点：≥13:00 开场的大点每天 ≤1——软罚非硬闸，双下午大点
#    仅在无他档时出现（同「上午一个点」哲学，罚 >> 全天走行）；
# ③ 大点先排：同日「大点开场晚于轻点」的逆序对计罚（大点先、
#    轻点后）——插入/打磨双向对称，与插入次序无关。
BIG_SITE_MIN_MINUTES = 80
BIG_SITE_ENTRY_CAP_MINUTES = 15 * 60 + 30
AFTERNOON_START_MINUTES = 13 * 60
# 近距同日圈（2026-11-07 用户拍板 5km 口径，plan 兜底层 _NEAR_SAMEDAY_KM
# 同源——本常量是唯一真值，agent.plan 引用它）：圈内=同片区连游，大点
# 贴邻同日不再按「第二个下午大点」判死（2026-11-08 城心簇拆天案：城心
# 180min+90min 两贴邻大点同日被 CP/插入/打磨/评分四路计罚 → untimed
# → 挪日 → 让位链删件，拆天链起点在此收口）。
NEAR_SAMEDAY_KM = 5.0
# 紧簇半径（2026-11-08 城心簇拆天案三拍·类级防护）：同街区级紧簇员
# （≤2km）与近距同日圈分档——紧簇=「距离聚合都是近距离聚合优先」的
# 硬档（plan 认领紧簇伴排序/愈合同位交换/终装审计共用；agent.plan
# _TIGHT_CLUSTER_KM 引用本真值）。
TIGHT_CLUSTER_KM = 2.0
AFTERNOON_ONE_BIG_PENALTY = 10_000
BIG_FIRST_PENALTY = 10_000
# 头档距离规则（2026-11-05 拍板「心愿单或者高排序的景点根据距离远近
# 可以排早上第一个，或者下午第一个景点」；同日二裁「上午头档应给
# 优先级更高且离酒店更远的点」——优先级（钉>tier）定谁争头档，距离
# （远者）定胜负，且换位必须有距离证据、缺数据不换）：钉住未排或
# tier≤2 高排序的非餐/酒店/演出/夜属性观光点为「头档候选」——候选
# 应占当日首个观光位（上午头档），其余候选吃下午头档；候选间钉住
# 优先、tier 升序、距日内酒店锚距离降序（远者吃头档）。solver 双路
# 的逆序（非候选占候选前、候选占 P 前）计软罚（量纲同大点先排）；
# 兜底层另有同口径的上午头档置换与排序镜像
# （plan._morning_head_displacement / 兜底排序键）。
HEAD_FIRST_PENALTY = 10_000
# 午餐软钉（2026-11-01 用户拍板修正：时刻最多提前或延后半小时、用餐
# 时长可缩短半小时）：初始排程的 12 点午餐锚是排程默认而非用户约束
# ——meal_flex=True（仅初次排程）时对 soft_pin 餐点开滑窗+时长区间
# （午餐另受 2026-11-03 拍板硬窗，见 _LUNCH_START_EARLIEST/LATEST）；
# 用户手钉（soft_pin=False）仍铁律 19 钉死。兜底层同口径的分层许可见
# plan._fallback_sequence_times。
# 系统餐软锚（2026-11-01 晚拍板「午饭/顺路餐厅/晚饭都不用钉死」）：系统
# 摆的餐件（午餐占位/自动顺路餐厅）pinned=False+soft_pin=True——非铁律
# 19（用户可拖/可改时/LLM 可挪），但排程域仍锚定落位：普通日 lo=hi=pin
# 零漂移，弹性日走软钉窗（午餐硬窗内滑+可缩至 30、晚餐 ±30 滑窗）；
# 完全无锚的自由餐会退回「10:30 排餐」事故（2026-10-25 评测集）。
_MEAL_FLEX_SLIDE_MINUTES = 30
_MEAL_FLEX_MIN_DURATION_MINUTES = 30
# 激活闸（2026-11-01）：当天存在 ≥150 分钟大点或 13:00 前场次的演出时
# 才动用软钉——普通日（60-120 分钟小点）零漂移（12:00 全时长），软钉
# 只在规则为之而设的场景（240 分钟级大点/12:30 场次挡午餐）生效。
_MEAL_FLEX_TRIGGER_DUR = 150
_LUNCH_PIN_FLEX_BEFORE_MIN = 15 * 60  # 15:00 前开餐的餐点才按午餐软钉
_EVENING_ONLY_OPEN_MINUTES = 17 * 60  # 仅晚间开放（夜游类）= 全窗开 ≥17:00
_EVENING_OK_CATEGORIES = {"food", "entertainment", "hotel", "transport"}
_EVENING_OK_BEST = {"evening", "sunset", "show"}

# 上午一个点（2026-11-03 用户规则「上午一般只排一个点」）：12 点前
# 开场的观光点（非餐/非酒店）每天 ≤1——排程偏好而非硬闸，双晨点仅在
# 无他档时出现（双 morning 窗点、场次绑死、用户多钉）。与「上午不许
# 空」（morning_fill + blank_morning 罚）合成「上午恰一个点」的完整
# 口径。CP 路径该罚 ×100 与走行目标同量纲；插入路径 10_000 压过单次
# 插入的走行差（≤百余分钟）。
MORNING_ONE_SITE_END_MINUTES = 12 * 60
MORNING_ONE_SITE_PENALTY = 10_000
# 演出场次偏好（2026-11-03 拍板「演出优先傍晚/晚场」）：场次起点
# ≥15:00 视为傍晚/晚场（首选），更早场次计软罚——演出若霸占上午会
# 连带触发「上午一个点」把其余观光点全罚到午后（Day4 远郊演出 11:00
# 事故形态）；上午名额留给观光点，演出收尾当日。晚场全不可行时照付
# 罚放行（软偏好不拦可行性）；用户钉住场次天然豁免（铁律 19：pinned
# 演出走锚点通道不进插入候选）。与 S5 无场次晚场默认 20:10 同哲学。
SHOW_LATE_SESSION_MINUTES = 15 * 60
SHOW_EARLY_SESSION_PENALTY = 10_000
# CITYWALK 下午场（2026-11-06 二拍「CITYWALK倾向于下午场。沉浸式主题
# 街区，倾向于下午四点以后第二场」）：普通街区（category=citywalk）开场
# 早于 13:00 计软罚；街区型演出块（名含「街区」的演出/娱乐/街区行——
# 沉浸式主题街区）开场早于 16:00 计软罚。与同日头拍「无场次
# 演出不默认晚场」正交：头拍废的是硬窗（20:10 开演域/17:00 地板），
# 本条是软倾向——早场物理可行时照付罚放行，不拦可行性；用户自钉有
# 时刻豁免（铁律 19）。CP ×100 与走行同量纲；插入路 10_000 压过单次
# 插入走行差。
CITYWALK_AFTERNOON_MINUTES = 13 * 60
THEME_BLOCK_AFTERNOON_MINUTES = 16 * 60
CITYWALK_AFTERNOON_PENALTY = 10_000
# 夜档贴排组合（2026-11-07 拍板「不是各排各卡，而是两卡贴排，作为一个
# SITE 排列组合」）：同日 ≤COMBO_BUNDLE_KM（贴邻圈口径）的夜档观光点
# （best_visit_time=evening/sunset/show，同 16:00 开场闸豁免面；用户自
# 钉有时刻豁免）与其最近邻普通观光点绑成一个排程单元——普通点紧贴在
# 夜档点开场前收尾（普通大点 13:00-16:00 → 主题街区 16:00-20:00 形
# 态），组合内部以走行分钟首尾相接，不吃上午头档；夜档点自身仍守
# 16:00 后开场倾向。物理装不下（转场窗/营业窗/餐窗卡死）时组合解绑，
# 两卡回普通插入各自落位，不拦当日可行性。
COMBO_BUNDLE_KM = 1.5
COMBO_GAP_PENALTY_PER_MIN = 200  # CP 路：组合内间隙/分钟（>走行×100，<平罚）
COMBO_ORDER_PENALTY = 10_000  # CP 路：夜档点先于同伴开场平罚（×100 同量纲）
COMBO_NIGHT_FLOOR_PENALTY = 10_000  # CP 路：组合夜档点 <16:00 开场平罚


def _is_morning_site(item: VisitItem) -> bool:
    """晨点判定（计费口径）：非餐/非酒店的观光/演出点（餐跟 12 点锚、
    入住卡非游览）；用户自钉且有时刻（铁律 19，同 generic_entry_cap 豁免
    面）不计——那是用户的安排不是引擎节奏，双钉双晨合法且不挤占后续
    自由点（2026-11-03 拍板组合：钉后大点仍进上午而非被罚到 16:30 后）。"""
    if item.pinned and item.start_time is not None:
        return False
    return (item.category or "") not in ("food", "hotel")


def _is_big_site(item: VisitItem) -> bool:
    """大点判定（2026-11-04 拍板口径，见 BIG_SITE_MIN_MINUTES 注块）：
    时长>80min、非街区（tier8）、非餐/酒店/演出、非夜属性的观光点；
    用户自钉且有时刻（铁律 19）不计。"""
    if item.pinned and item.start_time is not None:
        return False
    if (item.category or "") in ("food", "hotel", "entertainment"):
        return False
    if (item.best_visit_time or "") in _EVENING_OK_BEST:
        return False
    if item.tier == 8:
        return False
    return (item.duration_minutes or 0) > BIG_SITE_MIN_MINUTES


def _is_light_sight(item: VisitItem) -> bool:
    """轻点判定（大点先排的另一侧）：同豁免面、非大点的观光点——
    街区 tier8、≤80min 普通点、夜属性点都在内（大点应排在它们前面）。"""
    if item.pinned and item.start_time is not None:
        return False
    if (item.category or "") in ("food", "hotel", "entertainment"):
        return False
    return not _is_big_site(item)


def _is_theme_block(item: VisitItem) -> bool:
    """街区型演出块判定（2026-11-06 二拍「沉浸式主题街区倾向晚场」）：
    名含「街区」的演出/娱乐/街区行——沉浸式主题街区样本类，倾向
    16:00 后开场（日午后段第二场形态）。用户自钉有时刻（铁律 19）不
    计；普通餐食街（名无「街区」二字的美食街类）不在本判定内，走
    _is_citywalk 的 13:00 口径。同街族并卡后主卡名是锚站名（如邻近
    大点锚），「街区」在子站名上——2026-11-07 主题街区案：名与类别
    都扫到 stops 子站，族卡照样吃 16:00 后软罚。"""
    if item.pinned and item.start_time is not None:
        return False
    stops = list(item.stops or [])
    names = [(item.name or "")] + [(s.name or "") for s in stops]
    cats = [(item.category or "")] + [(s.category or "") for s in stops]
    if not any("街区" in n for n in names):
        return False
    return _is_show(item) or any(c in ("citywalk", "entertainment") for c in cats)


def _is_citywalk(item: VisitItem) -> bool:
    """普通街区判定（2026-11-06 二拍「CITYWALK倾向于下午场」）：
    category=citywalk 且非街区型演出块——美食街/古镇街区类，倾向
    13:00 后开场。用户自钉有时刻（铁律 19）不计。"""
    if (item.category or "") != "citywalk":
        return False
    return not _is_theme_block(item)


def _is_head_candidate(item: VisitItem) -> bool:
    """头档候选判定（2026-11-05 拍板，见 HEAD_FIRST_PENALTY 注块）：钉住
    或 tier≤2 高排序、非餐/酒店/演出/夜属性。用户自钉有时刻（铁律 19）
    不参与——那是用户的安排；钉住未排在 solver 域即不可行（_visit_spec
    返 None 整日交兜底层置换），本判定在 solver 双路实际只见非钉候选。"""
    if item.pinned and item.start_time is not None:
        return False
    if (item.category or "") in ("food", "hotel", "entertainment"):
        return False
    if (item.best_visit_time or "") in _EVENING_OK_BEST:
        return False
    return bool(item.pinned) or (item.tier is not None and item.tier <= 2)


def _haversine_km(a: GeoPoint, b: GeoPoint) -> float:
    lo1, la1, lo2, la2 = map(math.radians, (a.lon, a.lat, b.lon, b.lat))
    dlo, dla = lo2 - lo1, la2 - la1
    h = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def _adjacent_big_ids(bigs: list[VisitItem]) -> set[int]:
    """下午单大点贴邻豁免成员判定（2026-11-08 城心簇拆天案）：返回与
    当日另一大点直线 ≤NEAR_SAMEDAY_KM 的成员 id 集——圈内大点对=同
    片区连游，不计「第二个下午大点」（plan 兜底层 2026-11-07 城心簇
    同街大点案豁免的引擎侧镜像，CP/插入/打磨/评分四路共用）。缺坐标不
    豁免（保守）。"""
    ids: set[int] = set()
    for i in range(len(bigs)):
        if bigs[i].location is None:
            continue
        for j in range(i + 1, len(bigs)):
            if bigs[j].location is None:
                continue
            if _haversine_km(bigs[i].location, bigs[j].location) <= NEAR_SAMEDAY_KM:
                ids.add(id(bigs[i]))
                ids.add(id(bigs[j]))
    return ids


def tight_cluster_split_violations(days: list) -> list[str]:
    """终装紧簇审计（2026-11-08 城心簇拆天案三拍·类级防护）：检
    「距离聚合都是近距离聚合优先」不变量在成稿上的违例——紧簇员 v
    （与某日 D 内点位直线 ≤TIGHT_CLUSTER_KM）坐在别天，而 D 已满员
    （≥4 非演出参访）且坐着陌生人（与 D 其余点位全部 >NEAR_SAMEDAY_
    KM）。D 有空位时的拆分是认领梯子的合法结果（同日四拍「高 tier 地标
    要的」：tier 序合法占座不追改），不算违例；满员且无陌生人的拆分
    是容量所迫（4/日硬闸），也不算。违例=坐座顺序错：陌生人本该把
    座位让给紧簇员。缺坐标/演出/餐/酒店/交通件不参与。"""
    by_day: dict[int, list[VisitItem]] = {}
    for d in days:
        vs = [
            i
            for i in d.items
            if isinstance(i, VisitItem)
            and i.location is not None
            and not _is_show(i)
            and str(i.category or "") not in ("food", "hotel", "transport")
        ]
        by_day[d.day] = vs
    out: list[str] = []
    for d_day, vs in by_day.items():
        if len(vs) < 4:
            continue
        strangers = [
            w
            for w in vs
            if all(
                _haversine_km(w.location, o.location) > NEAR_SAMEDAY_KM
                for o in vs
                if o is not w
            )
        ]
        if not strangers:
            continue
        outsiders = [
            v
            for e_day, evs in by_day.items()
            if e_day != d_day
            for v in evs
            if any(
                _haversine_km(v.location, p.location) <= TIGHT_CLUSTER_KM for p in vs
            )
        ]
        for v in outsiders:
            out.append(
                f"day{d_day} 满员且坐着陌生人 "
                + "、".join(w.name for w in strangers)
                + f"，紧簇员「{v.name}」被拆到 day{v.day}"
            )
    return out


def _night_combo_pairs(specs: list["_VisitSpec"]) -> list[tuple[int, int]]:
    """夜档贴排组合对（2026-11-07 拍板「两卡贴排，作为一个 SITE 排列组
    合」）：夜档观光点（bvt=evening/sunset/show，同入场闸豁免面；2026-
    11-08 扩面：主题街区整类可作夜侧——「所有街区都可以作为夜场，也可
    以白天」；用户自钉有时刻豁免）与同日 ≤COMBO_BUNDLE_KM 的最近邻普
    通观光点（非餐/酒店/夜档/街区、非钉）各绑一对——返回 (a_idx,
    n_idx)，a=普通点应贴排在夜档点开场前收尾（普通大点 13:00-16:00 →
    主题街区 16:00-20:00 形态）。每夜档点至多绑最近一个；无坐标不绑。"""
    pairs: list[tuple[int, int]] = []
    for n_idx, sp_n in enumerate(specs):
        it_n = sp_n.item
        if it_n.pinned and it_n.start_time is not None:
            continue
        if (it_n.best_visit_time or "") not in _EVENING_OK_BEST and not _is_theme_block(
            it_n
        ):
            continue
        if (it_n.category or "") in ("food", "hotel"):
            continue
        if it_n.location is None:
            continue
        best: tuple[float, int] | None = None
        for a_idx, sp_a in enumerate(specs):
            it_a = sp_a.item
            if a_idx == n_idx:
                continue
            if (it_a.category or "") in ("food", "hotel"):
                continue
            if (it_a.best_visit_time or "") in _EVENING_OK_BEST:
                continue
            if _is_theme_block(it_a):
                continue  # 街区自己就是夜侧候选，不当白日锚
            if it_a.pinned and it_a.start_time is not None:
                continue
            if it_a.location is None:
                continue
            d = _haversine_km(it_a.location, it_n.location)
            if d > COMBO_BUNDLE_KM:
                continue
            if best is None or d < best[0]:
                best = (d, a_idx)
        if best is not None:
            pairs.append((best[1], n_idx))
    return pairs


def _hours_evening_only(window: PoiHours | None) -> bool:
    """夜游类场馆：所有开放段都从 17:00 后才开始（白天无档，不豁免则
    永远排不进）。白天开到晚间的场馆（如 07:30-18:00）不再豁免——
    2026-11-01 用户裁定除夜游与演出外一律最晚 16:30 入场（旧口径
    「闭馆 ≥17:30 即豁免」废除）。"""
    if window is None:
        return False
    if window.windows:
        return all(
            _to_minutes(opens) >= _EVENING_ONLY_OPEN_MINUTES
            for opens, _ in window.windows
        )
    if window.opens is None:
        return False
    return _to_minutes(window.opens) >= _EVENING_ONLY_OPEN_MINUTES


def generic_entry_cap(item: VisitItem, window: PoiHours | None) -> int | None:
    """非演出观光点的最晚开场分钟数；None = 不设闸（豁免面见常量注释）。

    2026-11-07 用户再拍板（第 5 次重述）：16:00 闸为「开场闸」——观光
    须 16:00 前安排（开场），时长可以自然跨过 16:00，营业窗 + 日终
    21:30 照卡（2026-11-05 的「结束闸=开场+时长≤16:30」口径作废——
    它把 240min 级大块头压成「必须上午整块开场」，大型综合体类下午档
    结构性无解）。大点 15:30 开场带（2026-11-04）保留为并列上限。"""
    if item.pinned and item.start_time is not None:
        # 铁律 19：用户确认过的时刻优先于默认排程规则。系统必去钉可能
        # 落在排不上时间的条目上（降级日）——无时刻即无「用户确认时刻」
        # 可豁免，照常走闸（2026-11-01 远郊大点 pinned+未排被兜底甩到
        # 18:00（闭馆 17:00）事故根因）。
        return None
    if (item.best_visit_time or "") in _EVENING_OK_BEST:
        return None
    if (item.category or "") in _EVENING_OK_CATEGORIES:
        return None
    if _hours_evening_only(window):
        return None
    if _is_theme_block(item):
        # 主题街区整类开晚场（2026-11-08 拍板「所有街区都可以作为夜场，
        # 也可以白天」）：不吃白天开场闸/大点 15:30 带——主题街区 240min
        # citywalk 形态此前被当大点压 15:30、又被兜底塞进白天 12:30。
        # 「建议晚上」由规则 33 软偏好（≥16:00 开场倾向）+ 夜组贴排
        # 表达，不是硬闸；白天照排合法。
        return None
    if _is_big_site(item):
        return BIG_SITE_ENTRY_CAP_MINUTES
    return _GENERIC_ENTRY_CAP_MINUTES


def _after_transfer_buffer(transfer: TransferItem, visit: VisitItem) -> int:
    """落地侧缓冲（2026-11-01 用户拍板「落地→酒店→到店 1 小时后出发；
    无酒店首停 ≥ 落地 2.5 小时」）：火车/飞机的到达侧，非餐/非酒店条目
    用 ARRIVAL_STOP_FLOOR_MINUTES 地板；酒店入住卡与餐饮沿用铁律 4 的
    90 分钟衔接缓冲；汽车/大巴双侧照旧 90。"""
    if transfer.mode not in ("train", "flight"):
        return INTERCITY_BUFFER_MINUTES
    if (visit.category or "") in ("hotel", "food"):
        return INTERCITY_BUFFER_MINUTES
    return ARRIVAL_STOP_FLOOR_MINUTES


def _norm_city_name(text: str | None) -> str:
    """城市侧闸用的城市规整（strip + 剥「市」尾）。"""
    return str(text or "").strip().removesuffix("市")


def _city_side(item: VisitItem, transfer: TransferItem) -> str | None:
    """转场城市侧闸（2026-11-02 沪→西安 15:38 火车、23:59 抵达案）：
    当天有城际转场时，条目只能落在其城市对应的物理段——到达城条目须
    在落地之后（"after"），出发城条目须在发车之前（"before"）。
    None = 不判：用户钉（铁律 19 优先于排程规则）、餐饮/酒店（餐位跟
    餐窗城、入住卡跟落地逻辑，各有专属城市口径）、城市缺信号、或条目
    城市与该腿两端都不一致（宁不加码，不可错拦）；退化腿（规整后
    from==to 且双端非空，环线大巴/脏数据）整腿不判——先匹配 to_city
    会把同城条目全判成 "after"，上午条目团灭、整天 None。
    """
    from_city = _norm_city_name(transfer.from_city)
    to_city = _norm_city_name(transfer.to_city)
    if from_city and to_city and from_city == to_city:
        return None
    if item.pinned:
        return None
    if (item.category or "") in ("food", "hotel"):
        return None
    vcity = _norm_city_name(item.city)
    if not vcity:
        return None
    if vcity == to_city:
        return "after"
    if vcity == from_city:
        return "before"
    return None


# 离城日上午闸（2026-11-03 拍板「LEAVING DATE IF TRAIN/BUS/FLIGHT IS IN
# THE AFTERNOON OR NIGHT, ARRANGE SITES IN THE MORNING BY DEFAULT / NO
# ARRANGEMENT」）：火车/大巴/飞机 ≥12:00（下午/夜晚）发车时，出发城条目
# 一律上午收尾（end ≤ min(12:00, 发车−90)），午后整段留白作赶车缓冲；
# <12:00（上午）发车整日无安排——cap=日始必令条目不可行，交挪日链迁走。
# 汽车腿时刻是引擎自排的弹性值不设闸（与 _after_transfer_buffer 的
# train/flight 专项口径同理）；用户钉（_city_side 已 None）与餐/酒店
# 天然豁免——铁律 19。
LEAVING_MORNING_END_MINUTES = 12 * 60
_LEAVING_DAY_MODES = frozenset({"train", "bus", "flight"})


def _leaving_morning_cap(mode: str | None, dep_min: int) -> int | None:
    """出发城条目在离城日的最晚收尾分钟数；None = 不设上午闸。"""
    if (mode or "") not in _LEAVING_DAY_MODES:
        return None
    if dep_min < LEAVING_MORNING_END_MINUTES:
        return DAY_START_MINUTES
    return min(LEAVING_MORNING_END_MINUTES, dep_min - INTERCITY_BUFFER_MINUTES)


_MINUTES_PER_DAY = 24 * 60


class _VisitSpec(NamedTuple):
    """Solved layout parameters for one VisitItem."""

    item: VisitItem
    lo: int  # earliest feasible start (minutes)
    hi: int  # latest feasible start (minutes)
    dur: int  # interval size upper bound (minutes)
    # G3 多段开窗（午休闭馆）：非 None 时 start 必须落其中一段
    # （solve_day 用条件约束 + ExactlyOne 建模，段外不可行）。
    windows: list[tuple[int, int]] | None = None
    # 2026-11-01 午餐软钉：时长可缩短时的下界（0=固定 dur——常规条目）。
    # 必须排在 windows 之后：位置构造 (item, lo, hi, dur, multi, dur_lo)。
    dur_lo: int = 0


def _to_minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def _to_time(minutes: int) -> time:
    return time(minutes // 60, minutes % 60)


def _visit_spec(
    item: VisitItem,
    hours: dict[str, PoiHours],
    *,
    meal_flex: bool = False,
) -> _VisitSpec | None:
    """Compute the start domain for a visit; None = provably infeasible."""
    dur = item.duration_minutes
    if dur is None:
        dur = DEFAULT_VISIT_MINUTES
    if dur <= 0:
        return None

    lo, hi = DAY_START_MINUTES, DAY_END_MINUTES - dur
    dur_lo = 0  # 0=固定时长；软钉午餐在 pinned 分支激活区间下界
    # 8.2.1：时段属性先收窄开窗（lo=max(窗起, 08:00)、hi=min(窗止, 21:00)-
    # dur），再依次与营业时间窗、pinned 锚点收紧。未知枚举值按 "any" 处理
    # 不约束（防御库脏数据）；food 类条目不带该字段（plan.py 走 pinned 餐
    # 窗），天然不受影响。
    # 2026-10-31：带真场次的演出按场次点开窗（下方 multi 通道承载），
    # 不再吃晚场替换——白天多场演出不再被硬塞固定晚窗。
    # pinned 演出仍走原域（铁律 19：用户钉的时间优先于场次表）。
    show_sessions = (
        show_session_starts(item.opening_hours)
        if _is_show(item) and not item.pinned
        else []
    )
    # 无场次演出按正常景点逻辑（2026-11-06 拍板）：best_visit="show" 不
    # 在 _BEST_VISIT_WINDOWS → 不加窗约束，营业窗/入场闸照常收口。
    best = _BEST_VISIT_WINDOWS.get(item.best_visit_time or "")
    if best is not None:
        lo = max(lo, best[0])
        hi = min(hi, best[1] - dur)
    window = hours.get(item.poi_id) if item.poi_id is not None else None
    cap = generic_entry_cap(item, window)
    if cap is not None:
        # 白天入场闸（2026-11-05 终裁=结束闸）：cap 已含时长回减，
        # 晚于它的开场必致 16:30 后仍在占用 → 不可行
        hi = min(hi, cap)
    multi: list[tuple[int, int]] | None = None
    if window is not None and window.windows:
        # G3：多段（如 09:00-12:00 + 13:30-17:00）——逐段与全天/best 窗
        # 相交，段内可行起点域 [seg_lo, seg_hi-dur]；存活段 >1 才多段建模。
        multi = []
        for opens, closes in window.windows:
            seg_lo = max(_to_minutes(opens), lo)
            seg_hi = min(_to_minutes(closes), hi + dur)
            if seg_lo <= seg_hi - dur:
                multi.append((seg_lo, seg_hi - dur))
        if not multi:
            return None
        lo, hi = min(s[0] for s in multi), max(s[1] for s in multi)
        if len(multi) == 1:
            lo, hi = multi[0]
            multi = None
    elif window is not None:
        lo = max(lo, _to_minutes(window.opens))
        hi = min(hi, _to_minutes(window.closes) - dur)

    if show_sessions:
        # 场次点窗：start 必恰落其中一个场次（段 (s, s)，G3 ExactlyOne 承载）
        multi = [(s, s) for s in show_sessions]

    # 系统餐软锚（2026-11-01 晚拍板「午饭/顺路餐厅/晚饭都不用钉死」）：
    # 未钉（pinned=False）但系统摆的餐件（soft_pin）仍以落位时刻为锚——
    # 不设铁律 19（用户可拖/可改时/LLM 可挪），但排程域锚定落位，防退
    # 回「10:30 排餐」自由漂移（2026-10-25 评测集事故）。
    soft_meal = (
        not item.pinned
        and item.soft_pin
        and (item.category or "") == "food"
        and item.start_time is not None
    )
    # 酒店入住卡同构软锚（2026-11-01 落地首停规则）：落位=到达酒店，
    # 排程域锚定不漂移；flex ±30 分支仍仅餐类，入住卡不参与。
    soft_hotel = (
        not item.pinned
        and item.soft_pin
        and (item.category or "") == "hotel"
        and item.start_time is not None
    )
    if item.pinned or soft_meal or soft_hotel:  # 铁律 19 / 系统软锚
        if item.start_time is None:
            return None
        pin = _to_minutes(item.start_time)
        # 日始 9 点（2026-10-31）是排程默认而非用户约束：用户自钉的
        # 早于日始的时刻照常生效（铁律 19 优先，validate_plan 另行提示）
        if pin < lo:
            lo = pin
        if multi is not None:
            if not any(s[0] <= pin <= s[1] for s in multi):
                return None
        elif not lo <= pin <= hi:
            return None
        if meal_flex and item.soft_pin and (item.category or "") == "food":
            # 软钉窗（仅初次排程 meal_flex=True）：午餐（<15:00 开餐且钉点
            # 在硬窗内）走开餐硬窗 [11:30, 12:30] + 时长可缩至 30
            # （2026-11-03 拍板；钉点已被挪出硬窗的不回拽，保可行）；
            # 其余 ±30 分钟滑窗（晚餐时长不变，2026-11-01 拍板「晚饭
            # 不用钉死」）。普通日/编辑路径 meal_flex=False → lo=hi=pin
            # 零漂移；用户手钉（soft_pin=False）照旧铁律 19 完全钉死。
            if pin < _LUNCH_PIN_FLEX_BEFORE_MIN and pin <= _to_minutes(
                LUNCH_START_LATEST
            ):
                lo = max(lo, _to_minutes(LUNCH_START_EARLIEST))
                hi = min(hi, _to_minutes(LUNCH_START_LATEST))
                dur_lo = LUNCH_DURATION_FLOOR_MINUTES
            else:
                lo = max(lo, pin - _MEAL_FLEX_SLIDE_MINUTES)
                hi = min(max(hi, pin), pin + _MEAL_FLEX_SLIDE_MINUTES)
                if pin < _LUNCH_PIN_FLEX_BEFORE_MIN:
                    dur_lo = _MEAL_FLEX_MIN_DURATION_MINUTES
        else:
            lo = hi = pin
        multi = None

    if lo > hi:
        return None
    return _VisitSpec(item, lo, hi, dur, multi, dur_lo)


def _fixed_transfer_window(item: TransferItem) -> tuple[int, int] | None:
    """Resolve a transfer to a fixed (start, duration); None = unusable."""
    if item.start_time is None:
        return None
    ts = _to_minutes(item.start_time)
    if item.end_time is not None:
        te = _to_minutes(item.end_time)
        if te <= ts or te >= _MINUTES_PER_DAY:
            return None
        return ts, te - ts
    dur = item.duration_minutes
    if dur is None or dur <= 0 or ts + dur >= _MINUTES_PER_DAY:
        return None
    return ts, dur


def _travel_cost(a: VisitItem, b: VisitItem, matrix: dict[tuple[str, str], int]) -> int:
    """Matrix lookup by poi_id pair, then item_id pair, else default."""
    if a.poi_id is not None and b.poi_id is not None:
        cost = matrix.get((a.poi_id, b.poi_id))
        if cost is not None:
            return cost
    cost = matrix.get((a.item_id, b.item_id))
    if cost is not None:
        return cost
    return DEFAULT_TRAVEL_MINUTES


def _head_pick(
    specs: list["_VisitSpec"],
    travel_minutes: dict[tuple[str, str], int] | None,
) -> VisitItem | None:
    """头档候选 P（2026-11-05 头档距离规则）：钉住优先、tier 升序、距
    日内酒店锚（矩阵走行分钟，无锚/无矩阵记 0）降序、时长降序；无候选
    返回 None。"""
    cands = [sp.item for sp in specs if _is_head_candidate(sp.item)]
    if not cands:
        return None
    anchor = next(
        (sp.item for sp in specs if (sp.item.category or "") == "hotel"), None
    )

    def _dist(v: VisitItem) -> int:
        if (
            travel_minutes is None
            or anchor is None
            or anchor is v
            or anchor.location is None
            or v.location is None
        ):
            return 0
        return _travel_cost(anchor, v, travel_minutes)

    return min(
        cands,
        key=lambda v: (
            0 if v.pinned else 1,
            v.tier if v.tier is not None else 11,
            -_dist(v),
            -(v.duration_minutes or DEFAULT_VISIT_MINUTES),
        ),
    )


def _add_travel_objective(
    model: cp_model.CpModel,
    specs: list[_VisitSpec],
    starts: list[cp_model.IntVar],
    travel_minutes: dict[tuple[str, str], int],
    *,
    separate: bool = False,
    sizes: list[object] | None = None,
    meal_penalty: object = 0,
    morning_penalty: object = 0,
    show_penalty: object = 0,
    afternoon_penalty: object = 0,
    inversion_penalty: object = 0,
    head_penalty: object = 0,
    cw_penalty: object = 0,
    combo_penalty: object = 0,
) -> None:
    """Minimise total travel between chronologically adjacent visits.

    Ordering is modelled with an AddCircuit tour over a dummy depot: the
    tour (minus depot arcs) is the visit sequence; each non-depot arc
    forces its head to start after its tail ends, so the tour order and
    the chronological order coincide.

    separate=True（2026-10-30）：弧约束再叠加相邻两点的走行分钟——旧版
    只把 travel 计进目标函数、不进时序约束，日程排得出「上一场 09:30
    散场、7.3km 外下一场 09:30 开场」的零走行衔接。分离态不可行时
    solve_day 直接弃日交上层兜底（2026-11-03：不再回落 gap=0 背靠背）。
    """
    n = len(specs)
    arcs: list[tuple[int, int, cp_model.IntVar]] = []
    costs = []
    for j in range(n):  # depot -> first visit
        lit = model.NewBoolVar(f"first_{j}")
        arcs.append((0, j + 1, lit))
    for i in range(n):  # last visit -> depot
        lit = model.NewBoolVar(f"last_{i}")
        arcs.append((i + 1, 0, lit))
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            lit = model.NewBoolVar(f"arc_{i}_{j}")
            arcs.append((i + 1, j + 1, lit))
            costs.append(
                lit * _travel_cost(specs[i].item, specs[j].item, travel_minutes)
            )
            gap = (
                _travel_cost(specs[i].item, specs[j].item, travel_minutes)
                if separate
                else 0
            )
            sz_i = sizes[i] if sizes is not None else specs[i].dur
            model.Add(starts[j] >= starts[i] + sz_i + gap).OnlyEnforceIf(lit)
    model.AddCircuit(arcs)
    # 软钉餐偏离惩罚（2026-11-01 规则：±30/缩 30 是许可不是偏好）：
    # travel×100 权重主导——省 ≥2 走行分钟才值得动午餐。上午超点罚/
    # 演出早场罚已在调用侧 ×100，与 travel 同量纲直接相加。
    model.Minimize(
        sum(costs) * 100
        + meal_penalty
        + morning_penalty
        + show_penalty
        + afternoon_penalty
        + inversion_penalty
        + head_penalty
        + cw_penalty
        + combo_penalty
    )


def _add_makespan_objective(
    model: cp_model.CpModel,
    specs: list[_VisitSpec],
    starts: list[cp_model.IntVar],
    transfers: list[tuple[TransferItem, int, int]],
    *,
    sizes: list[object] | None = None,
    meal_penalty: object = 0,
    morning_penalty: object = 0,
    show_penalty: object = 0,
    afternoon_penalty: object = 0,
    inversion_penalty: object = 0,
    head_penalty: object = 0,
    cw_penalty: object = 0,
    combo_penalty: object = 0,
) -> None:
    """Minimise the end of the last item of the day (earliest finish)."""
    # 弹性餐不计 makespan（2026-11-01）：餐不是日程的业务终点——缩餐/
    # 挪餐不再白嫖 makespan 收益；只有给参访腾结构空间时惩罚项才让位。
    # 纯餐日（无参访无交通）回退全员端点防空。
    _flexed = {i for i, sp in enumerate(specs) if sp.dur_lo and sp.dur_lo < sp.dur}
    _counted = [i for i in range(len(specs)) if i not in _flexed] or list(
        range(len(specs))
    )
    ends: list[cp_model.LinearExpr | int] = [
        starts[i] + (sizes[i] if sizes is not None else specs[i].dur) for i in _counted
    ]
    ends += [ts + tdur for _, ts, tdur in transfers]
    ub = max(
        [DAY_END_MINUTES]
        + [spec.hi + spec.dur for spec in specs]
        + [ts + tdur for _, ts, tdur in transfers]
    )
    makespan = model.NewIntVar(0, ub, "makespan")
    model.AddMaxEquality(makespan, ends)
    # 软钉餐偏离惩罚：makespan×100 权重主导（1 分钟 makespan > 最大偏离），
    # 无压力日零漂移+全时长。上午超点罚/演出早场罚（×100）优先于
    # makespan——「上午一个点」「演出优先傍晚/晚场」压过早收工偏好
    # （2026-11-03 拍板）。
    model.Minimize(
        makespan * 100
        + meal_penalty
        + morning_penalty
        + show_penalty
        + afternoon_penalty
        + inversion_penalty
        + head_penalty
        + cw_penalty
        + combo_penalty
    )


def solve_day(
    day: DayPlan,
    *,
    poi_hours: list[PoiHours],
    travel_minutes: dict[tuple[str, str], int] | None = None,
    time_budget_seconds: float = 3.0,
    meal_flex: bool = False,
) -> DayPlan | None:
    """Order and time one day's items; None = infeasible or timed out.

    Every input item must appear in the output (no drops); if the full
    set cannot be scheduled the day fails atomically and None is
    returned so the caller can enter the §6.9 degradation chain.
    """
    visits = [i for i in day.items if isinstance(i, VisitItem)]
    transfers = [i for i in day.items if isinstance(i, TransferItem)]
    if not visits and not transfers:
        return day.model_copy(deep=True)

    # 白天入场闸 16:30 全天候适用（2026-11-03 用户重申；转场日让位
    # 废除）——到达城条目装不下白闸的由挪日链 (_reconcile/_sweep) 迁移。
    transfer_windows: list[tuple[TransferItem, int, int]] = []
    for item in transfers:
        window = _fixed_transfer_window(item)
        if window is None:
            return None
        transfer_windows.append((item, window[0], window[1]))

    hours = {h.poi_id: h for h in poi_hours}
    # 激活闸：大点或早场次当天才 flex（普通日零漂移）
    flex_day = meal_flex and (
        any((v.duration_minutes or 0) >= _MEAL_FLEX_TRIGGER_DUR for v in visits)
        or any(
            _is_show(v)
            and any(s <= 13 * 60 for s in show_session_starts(v.opening_hours))
            for v in visits
        )
    )
    specs: list[_VisitSpec] = []
    for item in visits:
        spec = _visit_spec(item, hours, meal_flex=flex_day)
        if spec is None:
            return None
        specs.append(spec)

    def _attempt(separate: bool):
        """Build + solve the day model once; (solver, status, starts)."""
        model = cp_model.CpModel()
        starts: list[cp_model.IntVar] = []
        # 2026-11-01 午餐软钉：可缩时长的条目 size 是 IntVar（[dur_lo,dur]），
        # 其余沿用固定 int——输出端按类型取值。
        sizes: list[cp_model.IntVar | int] = []
        intervals: list[cp_model.IntervalVar] = []
        for spec in specs:
            start = model.NewIntVar(spec.lo, spec.hi, f"start_{spec.item.item_id}")
            starts.append(start)
            if spec.windows:
                # G3 多段开窗：start 必落其中一段（条件约束 + ExactlyOne，
                # 标准解法——不引入 optional intervals，模型更简）
                presences = []
                for j, (wlo, whi) in enumerate(spec.windows):
                    in_win = model.NewBoolVar(f"inwin_{spec.item.item_id}_{j}")
                    model.Add(start >= wlo).OnlyEnforceIf(in_win)
                    model.Add(start <= whi).OnlyEnforceIf(in_win)
                    presences.append(in_win)
                model.AddExactlyOne(presences)
            if spec.dur_lo and spec.dur_lo < spec.dur:
                size = model.NewIntVar(
                    spec.dur_lo, spec.dur, f"dur_{spec.item.item_id}"
                )
                sizes.append(size)
                # 本版 ortools 不收「双变量和」作 end——显式 end 变量+等式
                end = model.NewIntVar(
                    spec.lo + spec.dur_lo,
                    spec.hi + spec.dur,
                    f"end_{spec.item.item_id}",
                )
                model.Add(end == start + size)
                intervals.append(
                    model.NewIntervalVar(start, size, end, f"visit_{spec.item.item_id}")
                )
            else:
                sizes.append(spec.dur)
                intervals.append(
                    model.NewIntervalVar(
                        start, spec.dur, start + spec.dur, f"visit_{spec.item.item_id}"
                    )
                )
        for item, ts, tdur in transfer_windows:
            intervals.append(
                model.NewIntervalVar(ts, tdur, ts + tdur, f"transfer_{item.item_id}")
            )
        model.AddNoOverlap(intervals)

        # Visits keep INTERCITY_BUFFER_MINUTES clear on both sides of a
        # transfer; 落地侧首停地板（2026-11-01）：火车/飞机到达侧首个
        # 观光 ≥ 落地 +150（入住卡/餐饮贴常规 90 衔接缓冲）。
        for spec, start, size in zip(specs, starts, sizes):
            for titem, ts, tdur in transfer_windows:
                after_buf = _after_transfer_buffer(titem, spec.item)
                side = _city_side(spec.item, titem)
                if side == "after":
                    # 城市侧闸：到达城条目只能落在落地之后
                    model.Add(start >= ts + tdur + after_buf)
                    continue
                if side == "before":
                    # 城市侧闸：出发城条目只能落在发车之前
                    model.Add(start + size <= ts - INTERCITY_BUFFER_MINUTES)
                    # 离城日上午闸（2026-11-03 拍板）：火车/大巴/飞机
                    # ≥12:00 发车时出发城条目一律上午收尾（午后留白赶车），
                    # <12:00 发车整日无安排——装不下交挪日链，不硬排午后。
                    mcap = _leaving_morning_cap(titem.mode, ts)
                    if mcap is not None:
                        model.Add(start + size <= mcap)
                    continue
                before = model.NewBoolVar(f"before_{spec.item.item_id}_{ts}")
                model.Add(start + size <= ts - INTERCITY_BUFFER_MINUTES).OnlyEnforceIf(
                    before
                )
                model.Add(start >= ts + tdur + after_buf).OnlyEnforceIf(before.Not())

        # 软钉餐偏离惩罚项：|start-pin| + (dur - size)（激活软钉的餐才有）
        penalty_terms: list[object] = []
        for spec, start, size in zip(specs, starts, sizes):
            if not (spec.dur_lo and spec.dur_lo < spec.dur):
                continue
            pin = _to_minutes(spec.item.start_time) if spec.item.start_time else None
            if pin is None:
                continue
            drift = model.NewIntVar(
                0, _MEAL_FLEX_SLIDE_MINUTES, f"mdrift_{spec.item.item_id}"
            )
            model.AddAbsEquality(drift, start - pin)
            penalty_terms.append(drift + (spec.dur - size))
        meal_penalty = sum(penalty_terms) if penalty_terms else 0
        # 上午一个点（2026-11-03 拍板）：晨点（<12:00 开场、非餐/非酒店）
        # 超出 1 个的部分计软罚（×100 与 travel 目标同量纲——罚 >> 全天
        # 走行，正常日单晨点零罚；双 morning 窗/多钉无他档时照付罚放行）。
        morning_lits: list[cp_model.IntVar] = []
        for spec, start in zip(specs, starts):
            if not _is_morning_site(spec.item):
                continue
            lit = model.NewBoolVar(f"morn_{spec.item.item_id}")
            model.Add(start < MORNING_ONE_SITE_END_MINUTES).OnlyEnforceIf(lit)
            model.Add(start >= MORNING_ONE_SITE_END_MINUTES).OnlyEnforceIf(lit.Not())
            morning_lits.append(lit)
        morning_penalty: object = 0
        if len(morning_lits) > 1:
            extra = model.NewIntVar(0, len(morning_lits) - 1, "morn_extra")
            model.AddMaxEquality(extra, [sum(morning_lits) - 1, 0])
            morning_penalty = extra * (MORNING_ONE_SITE_PENALTY * 100)
        # 下午单大点 + 大点先排（2026-11-04 拍板，见 BIG_SITE_MIN_MINUTES
        # 注块）：≥13:00 开场的大点超出 1 个、或大点开场晚于轻点的逆序
        # 对，均计软罚（×100 与走行同量纲；双下午大点/逆序仅在无他档时
        # 照付罚放行，同「上午一个点」哲学）。
        # 贴邻豁免（2026-11-08 城心簇拆天案）：近距同日圈内成对大点=
        # 同片区连游，不计入下午超点——CP/插入/打磨/评分与 plan 兜底
        # 五路同口径。CP 侧为静态判定（对内豁免不依赖开场时刻）。
        _aft_adj_exempt = _adjacent_big_ids(
            [sp.item for sp in specs if _is_big_site(sp.item)]
        )
        afternoon_lits: list[cp_model.IntVar] = []
        for spec, start in zip(specs, starts):
            if not _is_big_site(spec.item):
                continue
            if id(spec.item) in _aft_adj_exempt:
                continue
            lit = model.NewBoolVar(f"aft_{spec.item.item_id}")
            model.Add(start >= AFTERNOON_START_MINUTES).OnlyEnforceIf(lit)
            model.Add(start < AFTERNOON_START_MINUTES).OnlyEnforceIf(lit.Not())
            afternoon_lits.append(lit)
        afternoon_penalty: object = 0
        if len(afternoon_lits) > 1:
            extra = model.NewIntVar(0, len(afternoon_lits) - 1, "aft_extra")
            model.AddMaxEquality(extra, [sum(afternoon_lits) - 1, 0])
            afternoon_penalty = extra * (AFTERNOON_ONE_BIG_PENALTY * 100)
        inv_lits: list[cp_model.IntVar] = []
        for spec_i, start_i in zip(specs, starts):
            if not _is_big_site(spec_i.item):
                continue
            for spec_j, start_j in zip(specs, starts):
                if spec_i is spec_j or not _is_light_sight(spec_j.item):
                    continue
                lit = model.NewBoolVar(
                    f"inv_{spec_i.item.item_id}_{spec_j.item.item_id}"
                )
                model.Add(start_i > start_j).OnlyEnforceIf(lit)
                model.Add(start_i <= start_j).OnlyEnforceIf(lit.Not())
                inv_lits.append(lit)
        inversion_penalty = sum(inv_lits) * (BIG_FIRST_PENALTY * 100) if inv_lits else 0
        # 头档距离规则（2026-11-05 拍板，见 HEAD_FIRST_PENALTY 注块）：
        # 头档候选 P 必须是当日首个开场观光点——任一非餐/酒店条目开场
        # 早于 P 计罚（×100 与走行同量纲；P 上午物理不可行时罚为常数
        # 不改择优，软偏好不拦可行性，同「上午一个点」哲学）。
        head_penalty: object = 0
        head_p = _head_pick(specs, travel_minutes)
        if head_p is not None:
            p_idx = next(i for i, sp in enumerate(specs) if sp.item is head_p)
            head_lits: list[cp_model.IntVar] = []
            for i, (spec_o, start_o) in enumerate(zip(specs, starts)):
                if i == p_idx or (spec_o.item.category or "") in ("food", "hotel"):
                    continue
                lit = model.NewBoolVar(f"head_{spec_o.item.item_id}")
                model.Add(start_o < starts[p_idx]).OnlyEnforceIf(lit)
                model.Add(start_o >= starts[p_idx]).OnlyEnforceIf(lit.Not())
                head_lits.append(lit)
            head_penalty = (
                sum(head_lits) * (HEAD_FIRST_PENALTY * 100) if head_lits else 0
            )
        # 演出场次偏好（2026-11-03 拍板「演出优先傍晚/晚场」）：多场次
        # 演出落 <15:00 场次计软罚（×100 与 travel/makespan 同量纲）——
        # 晚场可行时上午留给观光点。纯早场演出 lit 恒 1（罚为常数不改
        # 择优）；全晚场/单场演出域内 lit 恒 0；pinned 演出场次是用户
        # 安排（铁律 19），不走本罚。
        show_early_lits: list[cp_model.IntVar] = []
        for spec, start in zip(specs, starts):
            if not (
                _is_show(spec.item)
                and not spec.item.pinned
                and show_session_starts(spec.item.opening_hours)
            ):
                continue
            lit = model.NewBoolVar(f"show_early_{spec.item.item_id}")
            model.Add(start < SHOW_LATE_SESSION_MINUTES).OnlyEnforceIf(lit)
            model.Add(start >= SHOW_LATE_SESSION_MINUTES).OnlyEnforceIf(lit.Not())
            show_early_lits.append(lit)
        show_penalty: object = 0
        if show_early_lits:
            show_penalty = sum(show_early_lits) * (SHOW_EARLY_SESSION_PENALTY * 100)
        # CITYWALK 下午场（2026-11-06 二拍，见 CITYWALK_AFTERNOON_MINUTES
        # 注块）：普通街区 <13:00、街区型演出块 <16:00 开场计软罚（×100
        # 与 travel/makespan 同量纲）——早场可行但无他档时 lit 恒 1 罚为
        # 常数不改择优，软偏好不拦可行性；pinned 有时刻已在判定内豁免。
        cw_lits: list[cp_model.IntVar] = []
        blk_lits: list[cp_model.IntVar] = []
        for spec, start in zip(specs, starts):
            if spec.item.pinned and spec.item.start_time is not None:
                continue
            if _is_theme_block(spec.item):
                lit = model.NewBoolVar(f"blk_{spec.item.item_id}")
                model.Add(start < THEME_BLOCK_AFTERNOON_MINUTES).OnlyEnforceIf(lit)
                model.Add(start >= THEME_BLOCK_AFTERNOON_MINUTES).OnlyEnforceIf(
                    lit.Not()
                )
                blk_lits.append(lit)
            elif _is_citywalk(spec.item):
                lit = model.NewBoolVar(f"cw_{spec.item.item_id}")
                model.Add(start < CITYWALK_AFTERNOON_MINUTES).OnlyEnforceIf(lit)
                model.Add(start >= CITYWALK_AFTERNOON_MINUTES).OnlyEnforceIf(lit.Not())
                cw_lits.append(lit)
        cw_penalty: object = (
            (sum(cw_lits) + sum(blk_lits)) * (CITYWALK_AFTERNOON_PENALTY * 100)
            if cw_lits or blk_lits
            else 0
        )
        # 夜档贴排组合（2026-11-07 拍板「两卡贴排，作为一个 SITE 排列组
        # 合」）：普通点须贴排在夜档点开场前收尾——顺序颠倒平罚 + 组合内
        # 间隙分钟罚 + 夜档点早于 16:00 开场平罚；物理不可行时照付罚放行
        # （软偏好不拦可行性，同「上午一个点」哲学）。
        combo_penalty: object = 0
        for a_idx, n_idx in _night_combo_pairs(specs):
            it_a, it_n = specs[a_idx].item, specs[n_idx].item
            lit_ord = model.NewBoolVar(f"cord_{it_a.item_id}_{it_n.item_id}")
            model.Add(starts[n_idx] >= starts[a_idx] + sizes[a_idx]).OnlyEnforceIf(
                lit_ord
            )
            model.Add(starts[n_idx] < starts[a_idx] + sizes[a_idx]).OnlyEnforceIf(
                lit_ord.Not()
            )
            gap = model.NewIntVar(
                0, DAY_END_MINUTES, f"cgap_{it_a.item_id}_{it_n.item_id}"
            )
            model.Add(
                gap == starts[n_idx] - starts[a_idx] - sizes[a_idx]
            ).OnlyEnforceIf(lit_ord)
            lit_early = model.NewBoolVar(f"cfloor_{it_n.item_id}")
            model.Add(starts[n_idx] < THEME_BLOCK_AFTERNOON_MINUTES).OnlyEnforceIf(
                lit_early
            )
            model.Add(starts[n_idx] >= THEME_BLOCK_AFTERNOON_MINUTES).OnlyEnforceIf(
                lit_early.Not()
            )
            combo_penalty += (
                lit_ord * (COMBO_ORDER_PENALTY * 100)
                + gap * COMBO_GAP_PENALTY_PER_MIN
                + lit_early * (COMBO_NIGHT_FLOOR_PENALTY * 100)
            )
        if travel_minutes is not None and specs:
            _add_travel_objective(
                model,
                specs,
                starts,
                travel_minutes,
                separate=separate,
                sizes=sizes,
                meal_penalty=meal_penalty,
                morning_penalty=morning_penalty,
                show_penalty=show_penalty,
                afternoon_penalty=afternoon_penalty,
                inversion_penalty=inversion_penalty,
                head_penalty=head_penalty,
                cw_penalty=cw_penalty,
                combo_penalty=combo_penalty,
            )
        else:
            _add_makespan_objective(
                model,
                specs,
                starts,
                transfer_windows,
                sizes=sizes,
                meal_penalty=meal_penalty,
                morning_penalty=morning_penalty,
                show_penalty=show_penalty,
                afternoon_penalty=afternoon_penalty,
                inversion_penalty=inversion_penalty,
                head_penalty=head_penalty,
                cw_penalty=cw_penalty,
                combo_penalty=combo_penalty,
            )

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_budget_seconds
        solver.parameters.num_search_workers = 1  # deterministic schedules
        return solver, solver.Solve(model), starts, sizes

    solver, status, starts, sizes = _attempt(travel_minutes is not None and bool(specs))
    # 走行分离不可行（时段窗/转场缓冲卡死）不再回落 gap=0 背靠背语义
    # （2026-11-03 Day2 大点→城心大点 15:00 零车程事故拍板「零间隔不合法
    # 化」）：返回 None 交上层按日降级——_fallback_sequence_times 带腿
    # 重排、装不下留空披露（与 16:30 起始闸同口径）。
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    placed: list[tuple[int, VisitItem | TransferItem]] = []
    for spec, start, size in zip(specs, starts, sizes):
        s = solver.Value(start)
        d = solver.Value(size) if not isinstance(size, int) else size
        update: dict[str, object] = {
            "start_time": _to_time(s),
            "end_time": _to_time(s + d),
        }
        if d != spec.dur:
            # 午餐软钉缩时长：条目时长同步为实值（卡片/后续重排一致）
            update["duration_minutes"] = d
        placed.append((s, spec.item.model_copy(update=update)))
    for item, ts, tdur in transfer_windows:
        updates: dict[str, time] = {}
        if item.end_time is None:
            updates["end_time"] = _to_time(ts + tdur)
        placed.append((ts, item.model_copy(update=updates)))
    placed.sort(key=lambda pair: (pair[0], pair[1].item_id))
    return DayPlan(day=day.day, base_city=day.base_city, items=[i for _, i in placed])


def _candidate_starts(spec: "_VisitSpec") -> list[tuple[int, int]]:
    """条目可行起点域段（multi=场次点/多段窗，否则全天/best 域）。"""
    if spec.windows:
        return list(spec.windows)
    return [(spec.lo, spec.hi)]


def insertion_schedule_day(
    day: DayPlan,
    *,
    poi_hours: list[PoiHours],
    travel_minutes: dict[tuple[str, str], int] | None = None,
    meal_flex: bool = False,
) -> DayPlan | None:
    """锚点优先+最廉插入排时（PR2 主路，TTDP 经典做法）。

    2026-11-01《求解器升级建议》落地：确定性、零「不可行塌方」、O(n²)。
    ①锚点=transfers（±90 缓冲）+完全钉死项；②其余按时长降序最廉插入
    （所有空档×可行起点选「新增走行最小、并列最早」，窗/场次/入场闸/
    软钉餐位分层许可全判定）；③重定位打磨一轮。matrix 提供时相邻条目
    按走行分钟隔开（与 CP separate 模式同语义）；无 matrix 背靠背合法
    （NoOverlap 同语义）。None=当天有排不下的条目→调用方回落 CP。
    """
    visits = [i for i in day.items if isinstance(i, VisitItem)]
    transfers = [i for i in day.items if isinstance(i, TransferItem)]
    if not visits and not transfers:
        return day.model_copy(deep=True)

    # 白天入场闸 16:30 全天候适用（2026-11-03 用户重申；转场日让位
    # 废除）——到达城条目装不下白闸的由挪日链 (_reconcile/_sweep) 迁移。
    hours = {h.poi_id: h for h in poi_hours}
    flex_day = meal_flex and (
        any((v.duration_minutes or 0) >= _MEAL_FLEX_TRIGGER_DUR for v in visits)
        or any(
            _is_show(v)
            and any(s <= 13 * 60 for s in show_session_starts(v.opening_hours))
            for v in visits
        )
    )
    specs: list[_VisitSpec] = []
    for item in visits:
        spec = _visit_spec(item, hours, meal_flex=flex_day)
        if spec is None:
            return None
        specs.append(spec)

    day_end = 21 * 60 + 30  # 与 plan 兜底同口径（演出收尾可越 21:00）

    # ---- 头档距离规则（2026-11-05 拍板）：候选先插、距离降序 ----
    # P=最优先头档候选（钉住>tier 升序>距酒店锚降序>时长降序）；候选组
    # 排在最前插入，远的先吃上午头档。pinned 未排在 _visit_spec 已不可
    # 行（整日交兜底层置换），本组实际只有非钉 tier≤2 候选。
    _head_p = _head_pick(specs, travel_minutes)
    _head_anchor = next(
        (sp.item for sp in specs if (sp.item.category or "") == "hotel"), None
    )

    def _head_dist(s: _VisitSpec) -> int:
        if (
            travel_minutes is None
            or _head_anchor is None
            or not _is_head_candidate(s.item)
            or s.item is _head_anchor
            or _head_anchor.location is None
            or s.item.location is None
        ):
            return 0
        return _travel_cost(_head_anchor, s.item, travel_minutes)

    # ---- ① 锚点：transfers（±90 缓冲）+ 完全钉死项 ----
    occupied: list[tuple[int, int, object]] = []
    # 落地侧首停地板（同 _after_transfer_buffer 口径）：非餐/非酒店候选
    # 起点不得落 [te+90, te+150)——基础占用块已拦 <te+90 的重叠。
    arrival_floor_zones: list[tuple[int, int]] = []
    city_windows: list[tuple[TransferItem, int, int]] = []
    for item in transfers:
        window = _fixed_transfer_window(item)
        if window is None:
            return None
        ts, tdur = window
        city_windows.append((item, ts, ts + tdur))
        occupied.append(
            (ts - INTERCITY_BUFFER_MINUTES, ts + tdur + INTERCITY_BUFFER_MINUTES, item)
        )
        if item.mode in ("train", "flight"):
            arrival_floor_zones.append(
                (
                    ts + tdur + INTERCITY_BUFFER_MINUTES,
                    ts + tdur + ARRIVAL_STOP_FLOOR_MINUTES,
                )
            )
    rest: list[_VisitSpec] = []
    for spec in specs:
        flexed = flex_day and spec.dur_lo and spec.dur_lo < spec.dur
        if spec.lo == spec.hi and not spec.windows and not flexed:
            occupied.append((spec.lo, spec.lo + spec.dur, spec.item))
        else:
            rest.append(spec)
    occupied.sort(key=lambda o: o[0])

    def _travel(a, b) -> int:
        if travel_minutes is None:
            return 0
        return _travel_cost(a, b, travel_minutes)

    def _morning_extra_cost(t: int, item: VisitItem) -> int:
        # 上午一个点（2026-11-03 拍板）：候选会构成第二个（及以后）晨点
        # 时计罚——已占晨点含用户钉（钉本身不动，后续自由点让位午后）。
        if t >= MORNING_ONE_SITE_END_MINUTES or not _is_morning_site(item):
            return 0
        for os_, _oe, oitem in occupied:
            if (
                isinstance(oitem, VisitItem)
                and os_ < MORNING_ONE_SITE_END_MINUTES
                and _is_morning_site(oitem)
            ):
                return MORNING_ONE_SITE_PENALTY
        return 0

    def _show_early_cost(t: int, item: VisitItem) -> int:
        # 演出场次偏好（2026-11-03 拍板「演出优先傍晚/晚场」）：带真场次
        # 的演出早于 15:00 开场计罚——晚场可行时不占上午（上午名额留给
        # 观光点）；量纲同上午超点罚，压过单次插入走行差。pinned 演出走
        # 锚点通道不进本函数（铁律 19）。无场次演出按正常景点排（
        # 2026-11-06 拍板），不吃晚场偏好罚——与 CP 路径 show_early_lits
        # 的场次闸同口径。
        if t >= SHOW_LATE_SESSION_MINUTES or not _is_show(item):
            return 0
        if not show_session_starts(item.opening_hours):
            return 0
        return SHOW_EARLY_SESSION_PENALTY

    def _cw_afternoon_cost(t: int, item: VisitItem) -> int:
        # CITYWALK 下午场（2026-11-06 二拍）：普通街区 <13:00、街区型
        # 演出块 <16:00 开场计罚——量纲同早场罚，压过单次插入走行差。
        # pinned 有时刻走锚点通道不进本判定（铁律 19，判定内已豁免）。
        if item.pinned and item.start_time is not None:
            return 0
        if _is_theme_block(item):
            return (
                CITYWALK_AFTERNOON_PENALTY if t < THEME_BLOCK_AFTERNOON_MINUTES else 0
            )
        if _is_citywalk(item):
            return CITYWALK_AFTERNOON_PENALTY if t < CITYWALK_AFTERNOON_MINUTES else 0
        return 0

    def _afternoon_big_cost(t: int, item: VisitItem) -> int:
        # 下午单大点（2026-11-04 拍板）：候选会是当日第二个 ≥13:00 开场
        # 大点时计罚——豁免面与「上午一个点」一致（用户自钉有时刻不计，
        # 双钉合法且不挤占后续自由点）。罚 >> 单次插入走行差。贴邻豁免
        # （2026-11-08 城心簇拆天案）：与已排下午大点在近距同日圈
        # （NEAR_SAMEDAY_KM）内=同片区连游不计罚（与 plan 兜底层同口径）。
        if t < AFTERNOON_START_MINUTES or not _is_big_site(item):
            return 0
        for os_, _oe, oitem in occupied:
            if (
                isinstance(oitem, VisitItem)
                and oitem is not item
                and os_ >= AFTERNOON_START_MINUTES
                and _is_big_site(oitem)
                and not (
                    item.location is not None
                    and oitem.location is not None
                    and _haversine_km(item.location, oitem.location) <= NEAR_SAMEDAY_KM
                )
            ):
                return AFTERNOON_ONE_BIG_PENALTY
        return 0

    def _big_first_cost(t: int, item: VisitItem) -> int:
        # 大点先排（2026-11-04 拍板「先排大点，再排轻点」）：候选
        # 大点落在轻点之后、或候选轻点插到大点之前，均计罚——双向对称，
        # 任一插入次序造出的同对逆序同价；大点互排/轻点互排不算。
        big = _is_big_site(item)
        light = _is_light_sight(item)
        if not big and not light:
            return 0
        cost = 0
        for os_, _oe, oitem in occupied:
            if not isinstance(oitem, VisitItem):
                continue
            if big and _is_light_sight(oitem) and os_ < t:
                cost += BIG_FIRST_PENALTY
            elif light and _is_big_site(oitem) and os_ > t:
                cost += BIG_FIRST_PENALTY
        return cost

    def _head_first_cost(t: int, item: VisitItem) -> int:
        # 头档距离规则（2026-11-05 拍板）：非候选插到候选前、或候选插到
        # P（最优先候选）前，均计罚——双向对称，量纲同大点先排。插入序
        # 已让候选先插（_hkey），本罚守打磨/回填不逆序。
        if _head_p is None:
            return 0
        cost = 0
        for os_, _oe, oitem in occupied:
            if not isinstance(oitem, VisitItem):
                continue
            if (oitem.category or "") in ("food", "hotel"):
                continue
            if _is_head_candidate(oitem):
                if not _is_head_candidate(item) and os_ > t:
                    cost += HEAD_FIRST_PENALTY
                elif (
                    _is_head_candidate(item)
                    and item is not _head_p
                    and oitem is _head_p
                    and os_ > t
                ):
                    cost += HEAD_FIRST_PENALTY
        return cost

    # 软钉餐机动跨度（非餐条目的条件块）：餐可在 [P-30, P+30] 开餐、
    # 时长 [dur-30, dur]——其它条目要么在 P+30 前收尾（餐顺延接后），
    # 要么从 P+dur-60（最早缩餐终点）后开始。2026-11-01 ±30 规则。
    flex_pins: list[tuple[int, int]] = []
    for spec in rest:
        if (
            flex_day
            and spec.dur_lo
            and spec.dur_lo < spec.dur
            and spec.item.start_time is not None
        ):
            flex_pins.append((_to_minutes(spec.item.start_time), spec.dur))

    def _fits(t: int, dur: int, spec: _VisitSpec) -> bool:
        e = t + dur
        if e > day_end:
            return False
        cap = generic_entry_cap(spec.item, hours.get(spec.item.poi_id))
        if cap is not None and t > cap:
            return False
        is_flex_meal = spec.dur_lo and spec.dur_lo < spec.dur
        if (spec.item.category or "") not in ("food", "hotel"):
            for fs, fe in arrival_floor_zones:
                if fs <= t < fe:
                    return False
        for tr, ts_, te_ in city_windows:
            # 转场城市侧闸（2026-11-02）：到达城条目不得排在落地前
            # （含发车前的上午空窗）；出发城条目不得排在离城之后。
            side = _city_side(spec.item, tr)
            if side == "after" and t < te_:
                return False
            if side == "before":
                if e > ts_:
                    return False
                # 离城日上午闸（2026-11-03 拍板）：火车/大巴/飞机
                # ≥12:00 发车时出发城条目一律上午收尾，<12:00 发车
                # 整日无安排——与 CP 路/plan 兜底同口径。
                mcap = _leaving_morning_cap(tr.mode, ts_)
                if mcap is not None and e > mcap:
                    return False
        if not is_flex_meal:
            for pin, mdur in flex_pins:
                span_lo, span_hi = (
                    pin - _MEAL_FLEX_SLIDE_MINUTES,
                    (pin + _MEAL_FLEX_SLIDE_MINUTES + mdur),
                )
                if t < span_hi and e > span_lo:
                    if e <= pin + _MEAL_FLEX_SLIDE_MINUTES:
                        continue  # 餐顺延接后：合法
                    if t >= pin + mdur - 60:
                        continue  # 餐提前+缩短后开始：合法
                    return False
        for os_, oe_, oitem in occupied:
            if t < oe_ and e > os_:
                return False
            if isinstance(oitem, VisitItem) and travel_minutes is not None:
                if e <= os_ and os_ - e < _travel(spec.item, oitem):
                    return False
                if t >= oe_ and t - oe_ < _travel(oitem, spec.item):
                    return False
        return True

    def _added_travel(t: int, dur: int, item: VisitItem) -> int:
        # 换乘锚不参与走行记账（PR2 起矩阵+换乘日在此 AttributeError 必崩
        # →整日静默降级；与 _fits 的 isinstance 守卫同口径，2026-11-01 修）
        before = [o for o in occupied if o[1] <= t]
        after = [o for o in occupied if o[0] >= t + dur]
        added = 0
        if before and isinstance(before[-1][2], VisitItem):
            added += _travel(before[-1][2], item)
        if after and isinstance(after[0][2], VisitItem):
            added += _travel(item, after[0][2])
        return added

    def _try_insert(spec: _VisitSpec) -> int | None:
        """最廉插入：返回落位起点；软钉餐分层（全时长→±30 域→缩 30）。"""
        flexed = flex_day and spec.dur_lo and spec.dur_lo < spec.dur
        pin = (
            _to_minutes(spec.item.start_time)
            if spec.item.start_time is not None
            else None
        )
        durs = [spec.dur] + ([spec.dur_lo] if flexed else [])
        best: tuple[int, int, int] | None = None  # (added, t, dur)
        for dur in durs:
            for lo, hi in _candidate_starts(spec):
                if flexed and pin is not None:
                    lo_d = max(lo, pin - _MEAL_FLEX_SLIDE_MINUTES)
                    hi_d = min(hi, pin + _MEAL_FLEX_SLIDE_MINUTES)
                    starts = sorted(set(list(range(lo_d, hi_d + 1, 15)) + [pin]))
                else:
                    starts = list(range(lo, hi + 1))
                for t in starts:
                    if not _fits(t, dur, spec):
                        continue
                    key = (
                        _added_travel(t, dur, spec.item)
                        + _morning_extra_cost(t, spec.item)
                        + _show_early_cost(t, spec.item)
                        + _afternoon_big_cost(t, spec.item)
                        + _big_first_cost(t, spec.item)
                        + _head_first_cost(t, spec.item)
                        + _cw_afternoon_cost(t, spec.item),
                        t,
                    )
                    if best is None or key < (best[0], best[1]):
                        best = (key[0], t, dur)
            if best is not None and not flexed:
                break  # 常规条目首个时长命中即定（都同一 dur）
        if best is None:
            return None
        _, t, dur = best
        occupied.append((t, t + dur, spec.item))
        occupied.sort(key=lambda o: o[0])
        return t if dur == spec.dur else -(t + 1)  # 负数标记=缩时长落位

    # ---- ①b 夜档贴排组合锚定（2026-11-07 拍板「两卡贴排，作为一个
    # SITE 排列组合」）：夜档点按 16:00 后开场倾向先落位，普通点紧贴其
    # 开场前收尾（隔走行分钟，与 CP 弧约束同语义）；16:00 后无档退全域
    # 最早可行档（贴排优先于夜档倾向）；任一侧装不下即组合解绑留痕，
    # 两卡回普通插入各自落位。锚定组合不进 ② 插入序、不进 ③ 打磨。
    combo_anchored: set[str] = set()

    def _first_feasible(sp: _VisitSpec, floor: int | None) -> int | None:
        domains = [d for d in _candidate_starts(sp)]
        if floor is not None:
            floored = [(max(lo, floor), hi) for lo, hi in domains if hi >= floor]
            if floored:
                domains = floored
        for lo, hi in domains:
            for t in range(lo, hi + 1):
                if _fits(t, sp.dur, sp):
                    return t
        return None

    for a_idx, n_idx in _night_combo_pairs(specs):
        sp_a, sp_n = specs[a_idx], specs[n_idx]
        n_start = _first_feasible(sp_n, THEME_BLOCK_AFTERNOON_MINUTES)
        if n_start is None:
            n_start = _first_feasible(sp_n, None)
        if n_start is None:
            logger.info("plan: night-combo skip %s no feasible slot", sp_n.item.name)
            continue
        gap_min = _travel(sp_a.item, sp_n.item) if travel_minutes is not None else 0
        a_start = n_start - gap_min - sp_a.dur
        if a_start < sp_a.lo or not _fits(a_start, sp_a.dur, sp_a):
            logger.info(
                "plan: night-combo unbound %s+%s no contiguous slot",
                sp_a.item.name,
                sp_n.item.name,
            )
            continue
        occupied.append((a_start, a_start + sp_a.dur, sp_a.item))
        occupied.append((n_start, n_start + sp_n.dur, sp_n.item))
        occupied.sort(key=lambda o: o[0])
        combo_anchored.update((sp_a.item.item_id, sp_n.item.item_id))
        rest = [s for s in rest if s is not sp_a and s is not sp_n]
        logger.info(
            "plan: night-combo anchored %s %s-%s -> %s %s-%s",
            sp_a.item.name,
            _to_time(a_start),
            _to_time(a_start + sp_a.dur),
            sp_n.item.name,
            _to_time(n_start),
            _to_time(n_start + sp_n.dur),
        )

    # ---- ② 大点先插（难放优先），软钉餐最后（可让位） ----
    # 插入序叠加头档距离规则（2026-11-05）：候选组最先、组内距酒店锚
    # 降序（远的占上午头档），其后维持时长降序原口径。
    def _hkey(s: _VisitSpec) -> tuple:
        return (
            0 if (_head_p is not None and _is_head_candidate(s.item)) else 1,
            -_head_dist(s),
            -s.dur,
        )

    dur_overrides: dict[str, int] = {}
    unsched_meals: list[VisitItem] = []
    hard = [s for s in rest if not (flex_day and s.dur_lo and s.dur_lo < s.dur)]
    meals = [s for s in rest if s not in hard]
    for spec in sorted(hard, key=_hkey):
        marker = _try_insert(spec)
        if marker is None and (
            is_lunch_placeholder(spec.item) or is_dinner_placeholder(spec.item)
        ):
            # 占位餐卡同降级（上一条口径的硬排镜像）：非弹性日占位餐
            # 卡走 hard 序，开餐窗被晚场演出占死时同样不得作废整日
            # 参访解——降级为不排时刻占位。
            logger.info(
                "solver: meal slot infeasible day %s %s -> keep unscheduled",
                day.day,
                spec.item.name,
            )
            unsched_meals.append(spec.item)
            continue
        if marker is None:
            return None
        if marker < 0:
            dur_overrides[spec.item.item_id] = spec.dur_lo
    for spec in meals:
        marker = _try_insert(spec)
        if marker is None:
            # 餐卡降级不连坐（2026-11-08 远郊组合案根修）：晚饭开餐窗被晚场
            # 演出整窗占死（远郊演出 17:00-18:20 vs [17:00,18:00)）时，整
            # 日四件参访好解被一张餐卡作废→回落 CP/兜底→扫尾把组合件
            # 挪散。餐卡按「窗满丢餐/自由安排占位」口径降级为不排时刻
            # 占位（交调用方兜底排序），参访解保住。
            logger.info(
                "solver: meal slot infeasible day %s %s -> keep unscheduled",
                day.day,
                spec.item.name,
            )
            unsched_meals.append(spec.item)
            continue
        if marker < 0:
            entry = next(o for o in occupied if o[2] is spec.item)
            dur_overrides[spec.item.item_id] = entry[1] - entry[0]
        if marker < 0:
            entry = next(o for o in occupied if o[2] is spec.item)
            dur_overrides[spec.item.item_id] = entry[1] - entry[0]

    # ---- ③ 重定位打磨：单点挪洞降总走行（一轮，仅 matrix 模式） ----
    if travel_minutes is not None and len(occupied) > 2:

        def _total_travel() -> int:
            # occupied 已按 start 有序——直接取参访子列；上午一个点罚
            # （2026-11-03 拍板）计入总成本：打磨挪点不得靠双晨点省走行。
            # 下午单大点/大点先排（2026-11-04 拍板）同口径入账。
            ordered = [o[2] for o in occupied if isinstance(o[2], VisitItem)]
            travel = sum(
                _travel(ordered[i], ordered[i + 1]) for i in range(len(ordered) - 1)
            )
            mornings = sum(
                1
                for o in occupied
                if isinstance(o[2], VisitItem)
                and o[0] < MORNING_ONE_SITE_END_MINUTES
                and _is_morning_site(o[2])
            )
            # 贴邻豁免（2026-11-08 城心簇拆天案）：近距同日圈内成对
            # 下午大点不计超点——打磨挪点不得靠拆贴邻对省罚。
            _aft_entries = [
                o[2]
                for o in occupied
                if isinstance(o[2], VisitItem)
                and o[0] >= AFTERNOON_START_MINUTES
                and _is_big_site(o[2])
            ]
            _aft_ex = _adjacent_big_ids(_aft_entries)
            aft_bigs = sum(1 for x in _aft_entries if id(x) not in _aft_ex)
            inversions = sum(
                1
                for ob in occupied
                if isinstance(ob[2], VisitItem) and _is_big_site(ob[2])
                for ol in occupied
                if isinstance(ol[2], VisitItem)
                and ol[2] is not ob[2]
                and _is_light_sight(ol[2])
                and ob[0] > ol[0]
            )
            # 头档距离规则（2026-11-05 拍板）同口径入账：打磨挪点不得靠
            # 候选逆序省走行（非候选占候选前、候选占 P 前）。
            head_viol = 0
            if _head_p is not None:
                seq_h = [
                    o[2]
                    for o in occupied
                    if isinstance(o[2], VisitItem)
                    and (o[2].category or "") not in ("food", "hotel")
                ]
                for x in range(len(seq_h)):
                    for y in range(x + 1, len(seq_h)):
                        a, b = seq_h[x], seq_h[y]
                        if (not _is_head_candidate(a) and _is_head_candidate(b)) or (
                            b is _head_p and a is not _head_p and _is_head_candidate(a)
                        ):
                            head_viol += 1
            return (
                travel
                + max(0, mornings - 1) * MORNING_ONE_SITE_PENALTY
                + max(0, aft_bigs - 1) * AFTERNOON_ONE_BIG_PENALTY
                + inversions * BIG_FIRST_PENALTY
                + head_viol * HEAD_FIRST_PENALTY
            )

        base = _total_travel()
        for spec in specs:
            if spec.item.item_id in combo_anchored:
                continue  # 夜档贴排组合（①b）：贴排结构不参与打磨挪洞
            entry = next((o for o in occupied if o[2] is spec.item), None)
            if entry is None or spec.lo == spec.hi:
                continue
            dur = entry[1] - entry[0]
            occupied.remove(entry)
            best = None
            for lo, hi in _candidate_starts(spec):
                for t in range(lo, hi + 1):
                    if _fits(t, dur, spec):
                        added = (
                            _added_travel(t, dur, spec.item)
                            + _morning_extra_cost(t, spec.item)
                            + _afternoon_big_cost(t, spec.item)
                            + _big_first_cost(t, spec.item)
                            + _head_first_cost(t, spec.item)
                        )
                        if best is None or added < best[0]:
                            best = (added, t)
            if best is None:
                occupied.append(entry)  # 理论不可达（刚移出时可行）
                occupied.sort(key=lambda o: o[0])
                continue
            _, t = best
            occupied.append((t, t + dur, spec.item))
            occupied.sort(key=lambda o: o[0])
            if _total_travel() >= base:
                occupied.remove(next(o for o in occupied if o[2] is spec.item))
                occupied.append(entry)
                occupied.sort(key=lambda o: o[0])

    # ---- 输出 ----
    placed: list[tuple[int, object]] = []
    seen_transfers: set[str] = set()
    for os_, oe_, oitem in occupied:
        if isinstance(oitem, TransferItem):
            ts = os_ + INTERCITY_BUFFER_MINUTES
            placed.append((ts, oitem))
            seen_transfers.add(oitem.item_id)
        else:
            dur = dur_overrides.get(oitem.item_id, oe_ - os_)
            update: dict[str, object] = {
                "start_time": _to_time(os_),
                "end_time": _to_time(os_ + dur),
            }
            if dur != (oitem.duration_minutes or dur):
                update["duration_minutes"] = dur  # 软钉缩餐同步条目时长
            placed.append((os_, oitem.model_copy(update=update)))
    for item in transfers:
        if item.item_id not in seen_transfers:
            placed.append((_to_minutes(item.start_time), item))
    placed.sort(key=lambda pair: (pair[0], getattr(pair[1], "item_id", "")))
    for m in unsched_meals:
        placed.append((24 * 60, m))
    return DayPlan(day=day.day, base_city=day.base_city, items=[i for _, i in placed])


def solve_plan(
    plan: ItineraryPlan,
    *,
    poi_hours: list[PoiHours],
    travel_minutes: dict[tuple[str, str], int] | None = None,
    time_budget_seconds: float = 3.0,
    meal_flex: bool = False,
    scheduler: str | None = None,
) -> ItineraryPlan | None:
    """Solve every day independently; a failing day keeps its input layout.

    2026-10-31 上午空排事故：旧「单日失败作废整单」让一个过约束日
    （晚场演出+返程航班缓冲）把其余各天的好解一起拖进顺序兜底，
    第 2/3 天上午全空。现在失败日原样保留（未排时间的条目由调用方
    的 _fallback_sequence_times 逐日收口），其余天保住 solver 优化解；
    调用方以「还有无 untimed 参访」判定是否降级披露。
    """
    solved_days: list[DayPlan] = []
    # PR2（2026-11-01 用户批《求解器升级建议》）：插入式排时为主路
    # （确定性、零塌方、O(n²)）；CHINATRIP_SCHEDULER=cp 回旧 CP 主路做
    # 基准对照；插入失败的日回落 CP solve_day，再失败保输入（按日降级）。
    # scheduler 显式参数优先（编辑路径传 "cp" 保与历史会话幂等），
    # 缺省 env：insertion=插入主路（生成），cp=旧 CP 主路（A/B 基准）。
    mode = scheduler or os.environ.get("CHINATRIP_SCHEDULER", "insertion")
    use_insertion = mode != "cp"
    for day in plan.days:
        solved = None
        if use_insertion:
            solved = insertion_schedule_day(
                day,
                poi_hours=poi_hours,
                travel_minutes=travel_minutes,
                meal_flex=meal_flex,
            )
        if solved is None:
            solved = solve_day(
                day,
                poi_hours=poi_hours,
                travel_minutes=travel_minutes,
                time_budget_seconds=time_budget_seconds,
                meal_flex=meal_flex,
            )
        solved_days.append(solved if solved is not None else day.model_copy(deep=True))
    return plan.model_copy(update={"days": solved_days})


#: §6.9 names the pipeline entrypoint ``solve_itinerary``; it is the
#: whole-plan solve.
solve_itinerary = solve_plan
