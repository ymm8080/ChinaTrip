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
  -10（unknown 不罚，对齐 _rain_exposed 口径）；转场 -round(km)/30
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

DAY_VISIT_BUDGET_MINUTES = 360  # 对齐 agent.plan.DAY_VISIT_BUDGET_MINUTES
BUDGET_SLACK_MINUTES = 30  # 对齐晨间保底「360+30」容差（溢出 30 内免罚）
DAY_END_MINUTES = 21 * 60 + 30
ENTRY_CAP_MINUTES = 16 * 60 + 30  # 白天入场闸（10-31 拍板 16:00 → 11-01 修正 16:30）
LUNCH_ANCHOR_MINUTES = 12 * 60
LUNCH_WINDOW_END_MINUTES = 15 * 60  # <15:00 的餐=午餐（兜底层同口径）
LUNCH_GRACE_MINUTES = 30  # ±30 许可（2026-11-01 拍板）
DAY_BALANCE_TARGET_MINUTES = 180  # S2.2：最差活动日负载目标（max-min 轻量版）

PEN_UNTIMED = 100
PEN_BLANK_MORNING = 80
PEN_VIOLATION = 60
PEN_RAIN_EXPOSED = 15
PEN_RAIN_PARTIAL = 10
PEN_BUDGET_OVERFLOW_CAP = 30
PEN_DAY_BALANCE_CAP = 15
PEN_MORNING_CROWD = 12  # 上午超点：每多一个晨点（2026-11-03 拍板）
PEN_NO_ENTERTAINMENT = 40  # 零娱乐/程（2026-11-03 拍板，软偏好）
PEN_EARLY_SHOW = 12  # 演出早场：<15:00 开演的多场次演出（2026-11-03 拍板
# 「演出优先傍晚/晚场」，与 solver SHOW_LATE_SESSION_MINUTES 同口径）


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


def plan_score(
    plan: ItineraryPlan,
    rain_days: dict[str, set[int]] | None = None,
    heavy_rain_days: dict[str, set[int]] | None = None,
) -> PlanScore:
    rain = rain_days or {}
    heavy = heavy_rain_days or {}
    sc = PlanScore()
    untimed = blank = overlaps = overruns = late_entries = 0
    rain_no = rain_partial = 0
    overflow_days = 0
    overflow_pen = 0
    travel_km = 0.0
    lunch_drift_pen = 0
    lunch_drift_min = 0
    morning_crowd = 0
    early_shows = 0
    entertainment = 0
    has_sights = False
    act_loads: list[int] = []
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
        # 演出场次偏好（2026-11-03 拍板「演出优先傍晚/晚场」）：
        # <15:00 开演的演出计软罚——与 solver 插入/CP 路早场罚同向，
        # LNS 不再把演出挪回早场。用户自钉且有时刻不计（铁律 19，
        # 同 morning_crowd 豁免面）；无场次演出引擎默认晚场天然零罚。
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
        )
        if rainy:
            for v in visits:
                rk = str(v.rain_ok or "")
                if str(v.category or "") in ("food", "hotel"):
                    continue
                if rk in ("no", "false"):
                    rain_no += 1
                elif rk == "partial":
                    rain_partial += 1
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
            if (
                cat not in ("entertainment", "food", "hotel")
                and bvt not in ("show", "evening", "sunset")
                and s > ENTRY_CAP_MINUTES
            ):
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
    violations = overlaps + overruns + late_entries
    sc.hard = {
        "untimed": -PEN_UNTIMED * untimed,
        "blank_morning": -PEN_BLANK_MORNING * blank,
        "violations": -PEN_VIOLATION * violations,
    }
    sc.soft = {
        "rain_exposed": -(PEN_RAIN_EXPOSED * rain_no + PEN_RAIN_PARTIAL * rain_partial),
        "budget_overflow": -overflow_pen,
        "travel": -(round(travel_km) // 30),
        "lunch_drift": -lunch_drift_pen,
        "day_balance": -balance_pen,
        "morning_crowd": -PEN_MORNING_CROWD * morning_crowd,
        "early_show": -PEN_EARLY_SHOW * early_shows,
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
        "rain_exposed": rain_no + rain_partial,
        "budget_overflow_days": overflow_days,
        "travel_km": round(travel_km, 1),
        "lunch_drift_min": lunch_drift_min,
        "morning_crowd": morning_crowd,
        "early_show": early_shows,
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
