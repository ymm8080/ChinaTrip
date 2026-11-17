"""必去覆盖审计（request-coverage audit，2026-11-17）。

rules.py 校验行程自身的内部一致性（时间冲突/营业窗/衔接/节奏……）；本模块
补上「请求 vs 行程」的覆盖契约：用户点名的每个必去（must_visits）在最终
行程里必须满足三分律——

    已排进某天（含无时刻的想去卡） 或 落在 plan.unplaced 或 出现在披露文本里

三者皆无 = 静默丢失（2026-11-17 上海案：豫园/外滩必去无声消失——
assumptions 无让位披露、unplaced 也没有）。ensure_must_disclosure 对缺失项
自动补一条披露行——把「无声消失」机械地变成「至少有披露」，不改排期、
不动选点链（并行重构在途，选点/求解器区域不碰）。

纯函数：只依赖领域模型，无 I/O / LLM / DB。名字匹配认 全等 与「双胞胎
互含」——互含只在多出部分是通用修饰（城市/区域前缀 ≥2 字，或 古镇/景区/
博物院/ancient town 类通用尾缀）时算同体：中心大厦=上海中心大厦、朱家角=
朱家角古镇；外滩 ≠ 外滩源（尾缀「源」非通用，是不同景点——被排成别的
站点必须披露，不允许静默顶替）。中英文名（name/name_en）都认。与既有
coverage.py（premium 档覆盖/雨天建议）职责不同，互不依赖。
"""

from __future__ import annotations

import re

from app.services.itinerary.models import ItineraryPlan, UnplacedCandidate

_JUNK_RE = re.compile(r"[\s·、，。,.;；:：!！?？()（）\[\]【】「」\"'`\-—_]+")

#: 互含匹配的短侧最小长度（单字过泛，不认）。
_MIN_CONTAIN_CHARS = 2

#: 通用尾缀（削掉后仍是同一景点）：中文聚落/景区/场馆类 + 英文聚落类
#: （norm 后无空格，按拼接形态匹配）。尾缀「源/湾/村」这类**专名性后缀
#: 不列**——外滩源/外滩 是两个景点，互含不算同体。
_GENERIC_TAILS: tuple[str, ...] = (
    "古镇",
    "古城",
    "景区",
    "旅游区",
    "风景区",
    "度假区",
    "小镇",
    "水乡",
    "湿地",
    "广场",
    "博物馆",
    "博物院",
    "故里",
    "遗址",
    "ancienttown",
    "ancientcity",
    "watertown",
    "watervillage",
    "oldtown",
    "scenicarea",
    "museum",
)


def _norm(name: str | None) -> str:
    return _JUNK_RE.sub("", (name or "").strip().lower())


def _twin_cover(a: str, b: str) -> bool:
    """双胞胎互含判定：多出部分必须是通用修饰才算同一景点。

    - 前置修饰（long = X + short，X ≥2 字）：城市/区域前缀——上海中心大厦
      之于 中心大厦、杭州西湖 之于 西湖；
    - 后置通用尾缀（long = short + X，X 在 _GENERIC_TAILS）：朱家角古镇
      之于 朱家角、Zhujiajiao Ancient Town 之于 zhujiajiao；
    - 其余互含（含中段互含、≥1 字非通用余量）一律不算：外滩源 ≠ 外滩、
      北外滩 ≠ 外滩（余量 1 字）——被排成邻近的另一景点必须披露，不允许
      静默顶替。
    """
    if a == b:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) < _MIN_CONTAIN_CHARS or len(long) - len(short) < 2:
        return False
    if long.endswith(short):
        return True  # 前置修饰（X ≥2 字即认：城市/区域名不是专名性鉴别位）
    if long.startswith(short):
        return long[len(short) :] in _GENERIC_TAILS
    return False


def _name_matches(
    requested: str, actual: str | None, actual_en: str | None = None
) -> bool:
    a = _norm(requested)
    if not a:
        return False
    for cand in (actual, actual_en):
        b = _norm(cand)
        if not b:
            continue
        if _twin_cover(a, b):
            return True
    return False


def _scheduled_names(plan: ItineraryPlan) -> list[tuple[str, str | None]]:
    out: list[tuple[str, str | None]] = []
    for day in plan.days:
        for item in day.items:
            name = getattr(item, "name", None)
            if name is None:
                continue  # TransferItem 等无 name 的段卡不参与覆盖匹配
            out.append((name, getattr(item, "name_en", None)))
    return out


def _scheduled_entries(
    plan: ItineraryPlan,
) -> list[tuple[str | None, str, str | None]]:
    """已排条目 (poi_id, name, name_en)——TransferItem 等无 name 段卡不参与。"""
    out: list[tuple[str | None, str, str | None]] = []
    for day in plan.days:
        for item in day.items:
            name = getattr(item, "name", None)
            if name is None:
                continue
            out.append(
                (getattr(item, "poi_id", None), name, getattr(item, "name_en", None))
            )
    return out


def dedupe_unplaced_against_scheduled(
    plan: ItineraryPlan,
) -> list[UnplacedCandidate]:
    """已排卡不得同时挂在 unplaced（双在场；2026-11-17 基线排查实锤）。

    只做保守同体判定：poi_id 相同，或 规范名/name_en 全等。包含关系不算
    ——外滩 vs 外滩源是两个不同景点，互含会把合法 chip 误清（请求侧审计的
    双胞胎容忍是故意的不对称：请求模糊些防误报，chip 侧严格防误删）。
    原地收窄 plan.unplaced，返回被移除的重复项——站点已在行程里，chip 本身
    是脏数据，记日志即可、无披露必要。
    """
    sched = _scheduled_entries(plan)
    if not sched or not plan.unplaced:
        return []
    kept: list[UnplacedCandidate] = []
    removed: list[UnplacedCandidate] = []
    for u in plan.unplaced:
        un = _norm(u.name)
        ue = _norm(u.name_en)
        dup = any(
            (u.poi_id and pid and u.poi_id == pid)
            or (un and un == _norm(n))
            or (ue and ue == _norm(e))
            for pid, n, e in sched
        )
        (removed if dup else kept).append(u)
    if removed:
        plan.unplaced = kept
    return removed


def missing_must_visits(
    plan: ItineraryPlan,
    must_names: list[str] | None,
    *,
    disclosed: list[str] | None = None,
) -> list[str]:
    """返回既没排上、也不在 unplaced、也无任何披露的必去名（静默丢失集）。

    disclosed：行程 assumptions 之外的会话级披露文案（如 session.assumptions）。
    """
    if not must_names:
        return []
    scheduled = _scheduled_names(plan)
    unplaced = [(u.name, getattr(u, "name_en", None)) for u in (plan.unplaced or [])]
    texts = [t for t in list(plan.assumptions or []) + list(disclosed or []) if t]
    missing: list[str] = []
    for req in must_names:
        if any(_name_matches(req, n, e) for n, e in scheduled):
            continue
        if any(_name_matches(req, n, e) for n, e in unplaced):
            continue
        needle = _norm(req)
        if needle and any(needle in _norm(t) for t in texts):
            continue
        missing.append(req)
    return missing


def ensure_must_disclosure(
    plan: ItineraryPlan,
    must_names: list[str] | None,
    *,
    disclosed: list[str] | None = None,
) -> list[str]:
    """对静默丢失的必去补披露行；幂等（补过的行本身就是披露，二次不补）。

    返回本次新增的披露行（空列表 = 覆盖契约满足，无事发生）。
    """
    missing = missing_must_visits(plan, must_names, disclosed=disclosed)
    if not missing:
        return []
    lines = [
        f"必去「{name}」未排入行程，且此前无让位披露——覆盖审计自动补记"
        "（必去不允许无声消失）。"
        for name in missing
    ]
    plan.assumptions = list(plan.assumptions or []) + lines
    return lines
