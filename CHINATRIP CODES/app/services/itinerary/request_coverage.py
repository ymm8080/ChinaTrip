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

from app.services.itinerary.models import (
    ItineraryPlan,
    UnplacedCandidate,
    VisitItem,
)

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


def demote_untimed_musts(plan: ItineraryPlan, *, lang: str = "zh") -> list[str]:
    """B-01（2026-11-17 颐和园案）：必去的无时刻灰卡不是合法终态。

    出站闸里把这类卡降级成 unplaced（reason=must_unseated，day_hint=原天）
    并补披露——必去要么带时刻在场、要么可见地落在想去+披露，绝不挂灰卡。
    幂等：降级后灰卡不存在，二次运行为空。
    用户手钉卡（pinned、非 must；铁律 19）不降级——那是用户自己的安排，
    出站口径保留在行程里（test_untimed_response_strip）。
    """
    notes: list[str] = []
    for day in plan.days:
        for item in list(day.items):
            if not isinstance(item, VisitItem):
                continue
            if item.start_time is not None:
                continue
            if (item.category or "") in ("food", "hotel"):
                continue
            if not getattr(item, "must", False):
                continue
            known_poi = {u.poi_id for u in (plan.unplaced or []) if u.poi_id}
            known_names = {_norm(u.name) for u in (plan.unplaced or [])}
            day.items.remove(item)
            if item.poi_id and item.poi_id in known_poi:
                continue
            if _norm(item.name) in known_names:
                continue
            plan.unplaced = list(plan.unplaced or []) + [
                UnplacedCandidate(
                    name=item.name,
                    name_en=getattr(item, "name_en", None),
                    poi_id=item.poi_id,
                    category=item.category,
                    tier=item.tier,
                    duration_minutes=item.duration_minutes,
                    location=item.location,
                    city=item.city,
                    day_hint=item.day,
                    reason="must_unseated",
                )
            ]
            notes.append(
                (
                    f"必去「{item.name}」暂未排上时刻（当天排不下），已列入"
                    "想去——可指定其他日期或缩短停留后加回"
                )
                if lang != "en"
                else (
                    f"Must-visit '{item.name}' could not be timed today; "
                    "moved to wishlist — specify another day or shorter stay"
                )
            )
    return notes


def _distinct_must_needles(must_names: list[str]) -> list[str]:
    """点名必去去重后的规范名（互含算同体）——罗列判定用它数「一行里
    出现了几个点名必去」，同名异写（故宫/故宫博物院）不数成两个。"""
    out: list[str] = []
    for name in must_names:
        n = _norm(name)
        if not n:
            continue
        if not any(n in m or m in n for m in out):
            out.append(n)
    return out


def _dedicated_mentions(req: str, texts: list[str], needles: list[str]) -> bool:
    """这段文案是否对 req 构成「个别披露」。

    旧口径「名字出现在任何披露文案里就算」过于宽松（2026-11-17 上海
    一日游案）：『外滩、豫园、朱家角古镇…位于出发城市 上海，出发日只
    安排交通，未列入行程』把五个必去塞进一行通用规则话术——名字全在，
    用户却看不到针对任何一个的告知，审计据此沉默。收窄：文案提到
    ≥2 个点名必去 = 罗列行，对谁都不算披露；只提到请求名本身 =
    个别披露，照旧算（让位/未排入等单点文案不受影响）。
    """
    needle = _norm(req)
    if not needle:
        return False
    for t in texts:
        tn = _norm(t)
        if needle not in tn:
            continue
        if sum(1 for m in needles if m in tn) <= 1:
            return True
    return False


def missing_must_visits(
    plan: ItineraryPlan,
    must_names: list[str] | None,
    *,
    disclosed: list[str] | None = None,
) -> list[str]:
    """返回既没排上、也不在 unplaced、也无任何披露的必去名（静默丢失集）。

    disclosed：行程 assumptions 之外的会话级披露文案（如 session.assumptions）。
    披露只认「个别披露」（_dedicated_mentions）——罗列行不算。
    """
    if not must_names:
        return []
    scheduled = _scheduled_names(plan)
    unplaced = [(u.name, getattr(u, "name_en", None)) for u in (plan.unplaced or [])]
    texts = [t for t in list(plan.assumptions or []) + list(disclosed or []) if t]
    needles = _distinct_must_needles(must_names)
    missing: list[str] = []
    for req in must_names:
        if any(_name_matches(req, n, e) for n, e in scheduled):
            continue
        if any(_name_matches(req, n, e) for n, e in unplaced):
            continue
        if _dedicated_mentions(req, texts, needles):
            continue
        missing.append(req)
    return missing


def unarranged_must_visits(
    plan: ItineraryPlan, must_names: list[str] | None
) -> list[str]:
    """未排上必去名册（2026-11-17 一日游案）：点名必去里没有任何天卡承载
    的名字——含已落 unplaced（想去 chip）与静默丢失的。H5 拿它出非折叠
    横幅：assumptions 是折叠块用户看不见，「必去未排上」必须有一眼可见
    的告知面。纯函数；名字匹配与覆盖审计同源（双胞胎容忍）。"""
    if not must_names:
        return []
    scheduled = _scheduled_names(plan)
    return [
        req
        for req in must_names
        if not any(_name_matches(req, n, e) for n, e in scheduled)
    ]


def ensure_must_disclosure(
    plan: ItineraryPlan,
    must_names: list[str] | None,
    *,
    disclosed: list[str] | None = None,
    lang: str = "zh",
) -> list[str]:
    """对静默丢失的必去补披露行；幂等（补过的行本身就是披露，二次不补）。

    返回本次新增的披露行（空列表 = 覆盖契约满足，无事发生）。
    """
    missing = missing_must_visits(plan, must_names, disclosed=disclosed)
    if not missing:
        return []
    lines = [
        (
            f"必去「{name}」未排入行程，且此前无让位披露——覆盖审计自动补记"
            "（必去不允许无声消失）。"
            if (lang or "zh") != "en"
            else (
                f"Must-visit '{name}' is not on the itinerary and had no prior "
                "disclosure — coverage audit auto-logged it (must-visits are "
                "never silently dropped)."
            )
        )
        for name in missing
    ]
    plan.assumptions = list(plan.assumptions or []) + lines
    return lines
