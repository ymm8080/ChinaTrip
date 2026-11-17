"""必去覆盖审计（request-coverage audit，2026-11-17）。

rules.py 校验行程自身的内部一致性（时间冲突/营业窗/衔接/节奏……）；本模块
补上「请求 vs 行程」的覆盖契约：用户点名的每个必去（must_visits）在最终
行程里必须满足三分律——

    已排进某天（含无时刻的想去卡） 或 落在 plan.unplaced 或 出现在披露文本里

三者皆无 = 静默丢失（2026-11-17 上海案：豫园/外滩必去无声消失——
assumptions 无让位披露、unplaced 也没有）。ensure_must_disclosure 对缺失项
自动补一条披露行——把「无声消失」机械地变成「至少有披露」，不改排期、
不动选点链（并行重构在途，选点/求解器区域不碰）。

纯函数：只依赖领域模型，无 I/O / LLM / DB。名字匹配用保守互含（短侧
≥2 字），与选点层的包含关系双胞胎（外滩 ↔ 外滩万国建筑博览群）同语义；
中英文名（name/name_en）都认。与既有 coverage.py（premium 档覆盖/雨天
建议）职责不同，互不依赖。
"""

from __future__ import annotations

import re

from app.services.itinerary.models import ItineraryPlan

_JUNK_RE = re.compile(r"[\s·、，。,.;；:：!！?？()（）\[\]【】「」\"'`\-—_]+")

#: 互含匹配的短侧最小长度（单字过泛，不认）。
_MIN_CONTAIN_CHARS = 2


def _norm(name: str | None) -> str:
    return _JUNK_RE.sub("", (name or "").strip().lower())


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
        if a == b:
            return True
        if min(len(a), len(b)) >= _MIN_CONTAIN_CHARS and (a in b or b in a):
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
