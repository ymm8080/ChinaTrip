# -*- coding: utf-8 -*-
"""全局评分器（2026-11-01 设计稿「跨天全局重排层」S1+S2.2）。

纯函数模块：不 import agent 层（避免与 agent.plan 循环依赖），口径
与来源在注释里逐条标注。用途有二：
1. LNS 跨天重排（S2）的评估地基——让「哪个点放哪天」可比较；
2. 指标面板原始数据（untimed 率 / 空白上午 / 雨暴露 / 预算溢出）。

权重（设计稿 §3+§4-S2.2，2026-11-01 批准）：
- 硬：未排时间卡 -100/张；活动日空白上午 -80/天；硬违规 -60/项
- 软（用户拍板口径均为小惩罚）：预算溢出 -溢出分钟/10（30 分钟免罚
  额度对齐晨间保底 360+30 闸，上限 -30/天）；雨天露天 -15、半露天
  -10、未标注室内外 -5（2026-11-05 拍板，品类非室内的 unknown 行）；
  转场 -round(km)/30
  （代理口径，腿字段缺失记 0）；午餐漂移 -超±30 部分/10（对齐
  「午餐 ±30 许可」拍板）；日均衡 -缺口/30（S2.2 max-min 轻量版：
  最差活动日负载距 180 的缺口，交通日豁免，需 ≥2 个活动日，上限
  -15）；上午超点 -12/个（2026-11-03 拍板「上午一般只排一个点」：
  <12:00 开场的非餐/非酒店点超出 1 个的部分，与 blank_morning 合成
  「上午恰一个点」双向口径）；零娱乐 -40/程（2026-11-03 拍板「每个
  行程宜有一场娱乐」，同日更正 nice-to-have 非强制、每行程一次判定
  非按城/按日：全程无 entertainment/演出条目计一次，行程含游览点才
  计——纯交通/占位形态不罚；软罚即偏好信号，不设强制注入）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.itinerary.models import (
    ItineraryPlan,
    TransferItem,
    VisitItem,
)
from app.services.itinerary.solver import (
    NEAR_SAMEDAY_KM,
    _adjacent_big_ids,
    _haversine_km,
    show_session_starts,
)

DAY_VISIT_BUDGET_MINUTES = 360  # 对齐 agent.plan.DAY_VISIT_BUDGET_MINUTES
BUDGET_SLACK_MINUTES = 30  # 对齐晨间保底「360+30」容差（溢出 30 内免罚）
DAY_END_MINUTES = 21 * 60 + 30
# 白天入场结束闸（11-05 终裁）：观光占用须 16:30 前收尾
ENTRY_CAP_MINUTES = 16 * 60
# 大点开场带（11-04 拍板；2026-11-07 开场闸下保持并列上限）
ENTRY_CAP_BIG_MINUTES = 15 * 60 + 30
AFTERNOON_START_MINUTES = 13 * 60  # 下午起点（2026-11-04 拍板「下午单大点」）
# CITYWALK 下午场带（2026-11-06 二拍；与 solver 同名常量同口径）
CITYWALK_AFTERNOON_MINUTES = 13 * 60
THEME_BLOCK_AFTERNOON_MINUTES = 16 * 60
BIG_SITE_MIN_MINUTES = 80  # 大点时长下限（2026-11-04 拍板「超过80分钟」）
LUNCH_ANCHOR_MINUTES = 12 * 60
LUNCH_WINDOW_END_MINUTES = 15 * 60  # <15:00 的餐=午餐（兜底层同口径）
LUNCH_GRACE_MINUTES = 30  # ±30 许可（2026-11-01 拍板）
DAY_BALANCE_TARGET_MINUTES = 180  # S2.2：最差活动日负载目标（max-min 轻量版）

PEN_UNTIMED = 100
PEN_BLANK_MORNING = 80
PEN_VIOLATION = 60
PEN_RAIN_EXPOSED = 15
PEN_RAIN_PARTIAL = 10
PEN_RAIN_UNMARKED = 5  # 未标注室内外点落雨日（2026-11-05 拍板「雨天
# 上午不排室外点」古镇街区案）：轻罚让 LNS 不把未标注点挪进雨日，
# 也不反向硬推——罚值低于 partial，避免把未标注的潜在室内点错杀出雨日
PEN_BUDGET_OVERFLOW_CAP = 30
PEN_DAY_BALANCE_CAP = 15
PEN_MORNING_CROWD = 12  # 上午超点：每多一个晨点（2026-11-03 拍板）
PEN_NO_ENTERTAINMENT = 40  # 零娱乐/程（2026-11-03 拍板，软偏好）
PEN_EARLY_SHOW = 12  # 演出早场：<15:00 开演的多场次演出（2026-11-03 拍板
# 「演出优先傍晚/晚场」，与 solver SHOW_LATE_SESSION_MINUTES 同口径）
PEN_CITYWALK_MORNING = 12  # CITYWALK 早场：<13:00 开场的普通街区（2026-11-06
# 二拍「CITYWALK倾向于下午场」，与 solver CITYWALK_AFTERNOON_MINUTES 同向）
PEN_THEME_BLOCK_EARLY = 12  # 街区型演出块 <16:00 开场（2026-11-06 二拍
# 「沉浸式主题街区，倾向于下午四点以后第二场」，同 solver
# THEME_BLOCK_AFTERNOON_MINUTES 同向）
PEN_EDGE_DAY_HEAVY = 12  # 边日重磅（2026-11-03 拍板「重要景点不放在
# 到达/离开日」）：转场日上的 tier≤4 重磅点每件计罚；演出/餐/酒店
# 豁免（拍板明说那两天适合 SHOW——演出不算「重」）；pinned 铁律 19
# 不罚；tier=None（占位/老数据）不罚。
PEN_AFTERNOON_CROWD = 12  # 下午超点：每多一个 ≥13:00 开场的大点
# （2026-11-04 拍板「超过80分钟的一般下午就放一个」，与 solver
# AFTERNOON_ONE_BIG_PENALTY 同口径同向——LNS 不把第二个大点挪进下午）
PEN_LATE_BIG = 12  # 大点后置：每个「大点开场晚于轻点」逆序对
# （2026-11-04 拍板「先排大点再排轻点」（城心簇实录），与 solver
# BIG_FIRST_PENALTY 同口径同向——LNS 不把大点排到轻点之后）
PEN_ARRIVAL_DAY_BIG = 12  # 到达日大点（2026-11-05 拍板「到达第一天
# 不适合放大块头景点，只适合小景点或 CityWalk」）：到达侧腿（当天
# 队尾还跟游览内容的转场腿）之后排入 >80min 大点每件计罚；返程
# 压轴腿（腿在当天末尾）不算到达日；pinned 铁律 19/餐/酒店/演出/
# tier8 街区豁免（同 _is_big_visit 豁免面）。与 edge_day_heavy 同向
# 叠加——tier≤4 大点在到达日双罚，4A/3A 大点只吃本罚。
PEN_VENUE_STRAND = 60  # 场馆亲和拆簇罚（2026-11-08 远郊演出案）：有坐标
# 观光/演出件在当前日无 ≤NEAR_SAMEDAY_KM 同日圈伴、而同城另一日却有
# 圈内伴=被修复通道拆离场馆簇（LNS 为消超载把远郊演出挪市区日，
# 55km 脱簇在 travel 软项里只值 -2 拦不住）。每件计罚；量级刻意压过
# 单日软项收益上限（budget_overflow -30 + day_balance -15）——拆簇换
# 均衡不再免费，溢出时先溢簇外/低档弱卡。软罚不入 ok 口径：结构性
# 无解（全场次冲突、真装不下）时各候选同付，不拦可行性；拆簇侧的
# 让位/弹座另有 plan 层 _venue_anchor_on 演出软钉。


def _is_big_visit(v: VisitItem) -> bool:
    """大点判定（与 solver._is_big_site 同口径，2026-11-04 拍板）：
    时长>80min、非街区（tier8）、非餐/酒店/演出、非夜属性；用户自钉
    且有时刻（铁律 19）不计。"""
    if v.pinned and v.start_time is not None:
        return False
    if str(v.category or "") in ("food", "hotel", "entertainment"):
        return False
    if str(v.best_visit_time or "") in ("evening", "sunset", "show"):
        return False
    if v.tier == 8:
        return False
    return (v.duration_minutes or 0) > BIG_SITE_MIN_MINUTES


def _is_light_visit(v: VisitItem) -> bool:
    """轻点判定（大点先排另一侧，与 solver._is_light_sight 同口径）。"""
    if v.pinned and v.start_time is not None:
        return False
    if str(v.category or "") in ("food", "hotel", "entertainment"):
        return False
    return not _is_big_visit(v)


def _near_mate_km(v: VisitItem, visits: list[VisitItem]) -> float | None:
    """v 在 visits 里的最近圈内伴距离（0<km≤NEAR_SAMEDAY_KM，2026-11-08
    远郊演出案场馆亲和口径）；无圈内伴返回 None。零距不算伴——同点坐标
    =占位/城市质心共享，非真实簇证据（与 agent.plan._tight_cluster_mate_on
    拍板口径一致）。"""
    vloc = getattr(v, "location", None)
    if vloc is None or getattr(vloc, "lon", None) is None:
        return None
    best: float | None = None
    for w in visits:
        if w is v:
            continue
        wloc = getattr(w, "location", None)
        if wloc is None or getattr(wloc, "lon", None) is None:
            continue
        km = _haversine_km(vloc, wloc)
        if 0 < km <= NEAR_SAMEDAY_KM and (best is None or km < best):
            best = km
    return best


@dataclass
class PlanScore:
    hard: dict[str, int] = field(default_factory=dict)
    soft: dict[str, int] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.hard.values()) + sum(self.soft.values())

    @property
    def ok(self) -> bool:
        """硬惩罚全零=达标（LNS 触发口径：仅硬惩罚触发）。"""
        return all(v == 0 for v in self.hard.values())

    def summary(self) -> str:
        bits = [f"total={self.total}"]
        for k, v in {**self.hard, **self.soft}.items():
            if v:
                bits.append(f"{k}={v}")
        return " ".join(bits)


def _minutes(t) -> int | None:
    if t is None:
        return None
    return t.hour * 60 + t.minute


def _morning_occupied(day) -> bool:
    """与 agent.plan._morning_occupied 同口径：12:00 前有非餐饮条目
    开始（交通算占用；餐饮/无时刻不算）。"""
    for it in day.items:
        st = getattr(it, "start_time", None)
        if st is None or (st.hour, st.minute) >= (12, 0):
            continue
        if isinstance(it, TransferItem):
            return True
        if str(getattr(it, "category", "") or "") != "food":
            return True
    return False


def _is_theme_block_visit(v: VisitItem) -> bool:
    """街区型演出块（2026-11-06 二拍）：名含「街区」的演出/娱乐/街区行
    ——与 solver._is_theme_block 同口径的评分器本地镜像（pinned 铁律 19
    不计）。"""
    if v.pinned and v.start_time is not None:
        return False
    if "街区" not in (v.name or ""):
        return False
    return str(v.best_visit_time or "") == "show" or str(v.category or "") in (
        "entertainment",
        "citywalk",
    )


def _is_citywalk_visit(v: VisitItem) -> bool:
    """普通街区（2026-11-06 二拍）：category=citywalk 且非街区型演出块
    ——与 solver._is_citywalk 同口径的评分器本地镜像。"""
    return str(v.category or "") == "citywalk" and not _is_theme_block_visit(v)


def plan_score(
    plan: ItineraryPlan,
    rain_days: dict[str, set[int]] | None = None,
    heavy_rain_days: dict[str, set[int]] | None = None,
) -> PlanScore:
    rain = rain_days or {}
    heavy = heavy_rain_days or {}
    sc = PlanScore()
    untimed = blank = overlaps = overruns = late_entries = 0
    rain_no = rain_partial = rain_unmarked = 0
    overflow_days = 0
    overflow_pen = 0
    travel_km = 0.0
    lunch_drift_pen = 0
    lunch_drift_min = 0
    morning_crowd = 0
    afternoon_crowd = 0
    late_big = 0
    early_shows = 0
    cw_morning = 0
    cw_block_early = 0
    edge_heavy = 0
    arrival_big = 0
    entertainment = 0
    has_sights = False
    act_loads: list[int] = []
    # 场馆亲和采样（2026-11-08 远郊演出案第五刀）：按日收集有坐标观光件
    # 与转场抵达城，循环后跨日比对拆簇。
    geo_days: list[tuple[str, list[VisitItem], set[str]]] = []
    venue_strand = 0
    for day in plan.days:
        city = str(day.base_city or "").removesuffix("市")
        rainy = day.day in rain.get(city, ()) or day.day in heavy.get(city, ())
        visits = [i for i in day.items if isinstance(i, VisitItem)]
        # 未排时间卡（餐位/酒店卡同样要求有时刻）
        untimed += sum(1 for v in visits if v.start_time is None)
        # 活动日空白上午（hotel-only 日不算活动日——入住卡不占上午）
        has_activity = any(
            str(v.category or "") not in ("food", "hotel") for v in visits
        )
        if has_activity and not _morning_occupied(day):
            blank += 1
        # 零娱乐（2026-11-03 拍板，每行程一次判定非按日）：与
        # solver._is_show 同口径——category=entertainment 或
        # best_visit_time=show；行程含游览点才计（纯交通/占位不罚）。
        entertainment += sum(
            1
            for v in visits
            if str(v.category or "") == "entertainment"
            or str(v.best_visit_time or "") == "show"
        )
        has_sights = has_sights or has_activity
        # 上午一个点（2026-11-03 拍板「上午一般只排一个点」）：晨点
        # （<12:00 开场、非餐/非酒店）超出 1 个的部分计软罚；用户自钉
        # 且有时刻不计（铁律 19 用户安排，同 solver._is_morning_site 口径）。
        morning_sites = sum(
            1
            for v in visits
            if v.start_time is not None
            and not (v.pinned and v.start_time is not None)
            and _minutes(v.start_time) < LUNCH_ANCHOR_MINUTES
            and str(v.category or "") not in ("food", "hotel")
        )
        morning_crowd += max(0, morning_sites - 1)
        # 下午单大点 + 大点先排（2026-11-04 拍板）：与 solver 插入/CP
        # 路同向——下午（≥13:00 开场）大点超出 1 个、大点开场晚于轻点
        # 的逆序对均计软罚；豁免面同 _is_big_visit（pinned 铁律 19 不计）。
        # 贴邻豁免（2026-11-08 城心簇拆天案）：近距同日圈（NEAR_SAMEDAY_KM）
        # 内成对的下午大点=同片区连游，不计超点——与 solver/plan 兜底同
        # 口径，LNS 不把贴邻大点对拆天（城心簇贴邻大点对实录）。
        _aft_big_list = [
            v
            for v in visits
            if v.start_time is not None
            and _is_big_visit(v)
            and _minutes(v.start_time) >= AFTERNOON_START_MINUTES
        ]
        _aft_ex = _adjacent_big_ids(_aft_big_list)
        aft_bigs = sum(1 for x in _aft_big_list if id(x) not in _aft_ex)
        afternoon_crowd += max(0, aft_bigs - 1)
        big_starts = [
            _minutes(v.start_time)
            for v in visits
            if v.start_time is not None and _is_big_visit(v)
        ]
        light_starts = [
            _minutes(v.start_time)
            for v in visits
            if v.start_time is not None and _is_light_visit(v)
        ]
        late_big += sum(1 for bs in big_starts for ls in light_starts if bs > ls)
        # 演出场次偏好（2026-11-03 拍板「演出优先傍晚/晚场」）：
        # <15:00 开演的演出计软罚——与 solver 插入/CP 路早场罚同向，
        # LNS 不再把演出挪回早场。用户自钉且有时刻不计（铁律 19，
        # 同 morning_crowd 豁免面）。无场次演出不罚（2026-11-06 拍板：
        # 无场次按正常景点逻辑排，不再默认晚场——与 solver
        # _show_early_cost 的场次闸同口径）。
        early_shows += sum(
            1
            for v in visits
            if v.start_time is not None
            and not (v.pinned and v.start_time is not None)
            and _minutes(v.start_time) < 15 * 60
            and (
                str(v.category or "") == "entertainment"
                or str(v.best_visit_time or "") == "show"
            )
            and show_session_starts(v.opening_hours)
        )
        # CITYWALK 下午场（2026-11-06 二拍「CITYWALK倾向于下午场。沉浸
        # 式主题街区，倾向于下午四点以后第二场」）：普通街区 <13:00 开场、
        # 街区型演出块 <16:00 开场计软罚——与 solver CP/插入同向，LNS 不
        # 把街区挪回上午。pinned 有时刻不计（判定内已豁免，铁律 19）。
        cw_morning += sum(
            1
            for v in visits
            if v.start_time is not None
            and _is_citywalk_visit(v)
            and _minutes(v.start_time) < CITYWALK_AFTERNOON_MINUTES
        )
        cw_block_early += sum(
            1
            for v in visits
            if v.start_time is not None
            and _is_theme_block_visit(v)
            and _minutes(v.start_time) < THEME_BLOCK_AFTERNOON_MINUTES
        )
        # 边日重磅（2026-11-03 拍板「重要景点不放在到达/离开日」）：带
        # 转场腿的天上出现 tier≤4 重磅点计软罚——LNS 跨天重排会把重磅
        # 挪去无转场的整天，把街区/演出留给边日。时刻无关（排布偏好，
        # 非时间违规）；pinned/餐/酒店/演出豁免。
        if any(isinstance(i, TransferItem) for i in day.items):
            edge_heavy += sum(
                1
                for v in visits
                if not v.pinned
                and (v.tier or 11) <= 4
                and str(v.category or "") not in ("food", "hotel", "entertainment")
                and str(v.best_visit_time or "") != "show"
            )
        # 到达日大点（2026-11-05 拍板）：到达侧=后面还跟游览内容的转场
        # 腿（day1 进城腿在队首、中段换城腿后接内容）；返程腿压轴的天
        # 是离城日不算——大点落返程日不罚（离城日另有上午闸铁律 21）。
        if any(
            isinstance(i, TransferItem) and j < len(day.items) - 1
            for j, i in enumerate(day.items)
        ):
            arrival_big += sum(1 for v in visits if _is_big_visit(v))
        if rainy:
            for v in visits:
                rk = str(v.rain_ok or "")
                if str(v.category or "") in ("food", "hotel"):
                    continue
                if rk in ("no", "false"):
                    rain_no += 1
                elif rk == "partial":
                    rain_partial += 1
                elif rk == "" and str(v.category or "") not in (
                    "museum",
                    "gallery",
                    "entertainment",
                ):
                    rain_unmarked += 1
        # 预算溢出（360=偏好：30 分钟免罚，超出部分 /10，上限 -30/天）
        load = sum(
            v.duration_minutes or 0
            for v in visits
            if str(v.category or "") not in ("food", "hotel")
        )
        over = load - (DAY_VISIT_BUDGET_MINUTES + BUDGET_SLACK_MINUTES)
        if over > 0:
            overflow_days += 1
            overflow_pen += min(PEN_BUDGET_OVERFLOW_CAP, over // 10)
        # 日均衡采样（S2.2）：活动日且非交通日才参与最差日比较
        if has_activity and not any(isinstance(i, TransferItem) for i in day.items):
            act_loads.append(load)
        geo_days.append(
            (
                city,
                [
                    v
                    for v in visits
                    if str(v.category or "") not in ("food", "hotel")
                    and getattr(v, "location", None) is not None
                ],
                {
                    str(t.to_city or "").strip().removesuffix("市")
                    for t in day.items
                    if isinstance(t, TransferItem)
                },
            )
        )
        timed = sorted(
            (v for v in visits if v.start_time is not None),
            key=lambda v: v.start_time,
        )
        spans = []
        for v in timed:
            s = _minutes(v.start_time)
            e = _minutes(v.end_time)
            if e is None:
                e = s + (v.duration_minutes or 60)
            spans.append((s, e))
            if e > DAY_END_MINUTES:
                overruns += 1
            cat = str(v.category or "")
            bvt = str(v.best_visit_time or "")
            # 白天入场开场闸（2026-11-07 用户再拍板，与 solver
            # generic_entry_cap 同口径）：观光 16:00 前未安排即迟——时长
            # 可跨界收尾（营业窗+日终照卡）；大点（>80min，tier8 街区
            # 豁免同 solver._is_big_site）走 15:30 开场带并列上限。
            if (
                cat not in ("entertainment", "food", "hotel")
                and bvt not in ("show", "evening", "sunset")
                # 主题街区整类开晚场（2026-11-08 拍板「所有街区都可以
                # 作为夜场，也可以白天」）——不吃白天入场闸，同 solver
                # generic_entry_cap 豁免面。
                and not _is_theme_block_visit(v)
                and v.start_time is not None
            ):
                entry_cap = ENTRY_CAP_MINUTES
                try:
                    dur_v = int(v.duration_minutes or 0)
                except (TypeError, ValueError):
                    dur_v = 0
                if dur_v > BIG_SITE_MIN_MINUTES and getattr(v, "tier", None) != 8:
                    entry_cap = ENTRY_CAP_BIG_MINUTES
                if (v.start_time.hour * 60 + v.start_time.minute) > entry_cap:
                    late_entries += 1
            km = getattr(v, "distance_to_next_km", None)
            if km:
                travel_km += float(km)
            if cat == "food" and s < LUNCH_WINDOW_END_MINUTES:
                drift = abs(s - LUNCH_ANCHOR_MINUTES)
                if drift > LUNCH_GRACE_MINUTES:
                    lunch_drift_min += drift - LUNCH_GRACE_MINUTES
                    lunch_drift_pen += (drift - LUNCH_GRACE_MINUTES) // 10
        for i in range(len(spans) - 1):
            if spans[i + 1][0] < spans[i][1]:
                overlaps += 1
    # 日均衡（S2.2，max-min 轻量版）：≥2 个活动日才比较，交通日豁免
    balance_pen = 0
    worst_day_load = -1
    if len(act_loads) >= 2:
        worst_day_load = min(act_loads)
        if worst_day_load < DAY_BALANCE_TARGET_MINUTES:
            balance_pen = min(
                PEN_DAY_BALANCE_CAP,
                (DAY_BALANCE_TARGET_MINUTES - worst_day_load) // 30,
            )
    # 场馆亲和拆簇（2026-11-08 远郊演出案第五刀）：当前日无圈内伴、而同城
    # 另一日（宿主闸口径同 LNS _day_hosts：base 同城或转场抵达该城）有
    # 圈内伴=拆离场馆簇——LNS/挪天修复为消超载拆簇要付大代价，溢出先
    # 溢簇外/低档弱卡。城市缺信号不罚（宁漏勿错）。
    for _di, (_dcity, _dvisits, _darr) in enumerate(geo_days):
        for _v in _dvisits:
            if _near_mate_km(_v, _dvisits) is not None:
                continue  # 当前日圈内成伴=锚定
            _vc = str(_v.city or "").strip().removesuffix("市") or _dcity
            if not _vc:
                continue
            for _dj, (_c2, _v2s, _a2) in enumerate(geo_days):
                if _dj == _di or not (_c2 == _vc or _vc in _a2):
                    continue
                if _near_mate_km(_v, _v2s) is not None:
                    venue_strand += 1
                    break
    violations = overlaps + overruns + late_entries
    sc.hard = {
        "untimed": -PEN_UNTIMED * untimed,
        "blank_morning": -PEN_BLANK_MORNING * blank,
        "violations": -PEN_VIOLATION * violations,
    }
    sc.soft = {
        "rain_exposed": -(
            PEN_RAIN_EXPOSED * rain_no
            + PEN_RAIN_PARTIAL * rain_partial
            + PEN_RAIN_UNMARKED * rain_unmarked
        ),
        "budget_overflow": -overflow_pen,
        "travel": -(round(travel_km) // 30),
        "lunch_drift": -lunch_drift_pen,
        "day_balance": -balance_pen,
        "morning_crowd": -PEN_MORNING_CROWD * morning_crowd,
        "afternoon_crowd": -PEN_AFTERNOON_CROWD * afternoon_crowd,
        "late_big": -PEN_LATE_BIG * late_big,
        "early_show": -PEN_EARLY_SHOW * early_shows,
        "citywalk_morning": -PEN_CITYWALK_MORNING * cw_morning,
        "theme_block_early": -PEN_THEME_BLOCK_EARLY * cw_block_early,
        "edge_day_heavy": -PEN_EDGE_DAY_HEAVY * edge_heavy,
        "arrival_day_big": -PEN_ARRIVAL_DAY_BIG * arrival_big,
        "venue_strand": -PEN_VENUE_STRAND * venue_strand,
        "no_entertainment": (
            -PEN_NO_ENTERTAINMENT if (has_sights and entertainment == 0) else 0
        ),
    }
    sc.counts = {
        "untimed": untimed,
        "blank_morning": blank,
        "violations": violations,
        "overlaps": overlaps,
        "overruns": overruns,
        "late_entries": late_entries,
        "rain_exposed": rain_no + rain_partial + rain_unmarked,
        "budget_overflow_days": overflow_days,
        "travel_km": round(travel_km, 1),
        "lunch_drift_min": lunch_drift_min,
        "morning_crowd": morning_crowd,
        "afternoon_crowd": afternoon_crowd,
        "late_big": late_big,
        "early_show": early_shows,
        "citywalk_morning": cw_morning,
        "theme_block_early": cw_block_early,
        "edge_day_heavy": edge_heavy,
        "arrival_day_big": arrival_big,
        "venue_strand": venue_strand,
        "entertainment": entertainment,
        "worst_day_load": worst_day_load,
    }
    return sc


def score_payload(
    payload: dict,
    rain_days: dict[str, set[int]] | None = None,
    heavy_rain_days: dict[str, set[int]] | None = None,
) -> PlanScore:
    """API/存档 JSON（model_dump 形状）直接打分——冒烟与指标面板用。"""
    plan = ItineraryPlan.model_validate(payload)
    return plan_score(plan, rain_days=rain_days, heavy_rain_days=heavy_rain_days)
