# -*- coding: utf-8 -*-
"""POI 全字段合并策略层（DB-free 纯函数，可无 PG 单测）。

口径（2026-11-24 用户拍板）：**「TWO ENTRIES ARE IN POIS TABLE. MAKE
SURE THE ONE LEFT HAS ALL INFORMATION IN ALL TWO ENTRIES」**——退役一条或多条，
幸存行吸收全部行的信息。与既有 ``poi_ingest.merge_place``（约 14 列、只填空）
的区别：本模块按 ``pois`` 全 78 列逐列处置，空值回填 / 数组并集 /
互补长文本拼接 / 时间戳取新 / 单值取信息量更大者 / 标量冲突留台账。

设计约束：
  1. **不依赖 DB、不依赖 SQLAlchemy**：只吃 dict/list，纯函数可单测；
     写库、快照、引用重指向、候选发现都由 ``app.jobs.dedupe_pois`` 承担。
  2. **schema 漂移闸**：``assert_full_column_coverage`` 要求 information_schema
     里每个 pois 列都在 ``COLUMN_POLICIES`` 中，未知列直接抛错，杜绝旧脚本
     「未知列静默落 keep_scalar → 退役行信息无声丢失」。
  3. **无硬编码对象**：不写死 UUID / 城市 / 别名 / loser_source；
     ``build_alias_union`` 的 ``extra`` 默认空（鸟巢一次性脚本的
     ``SHORT_ALIASES=("鸟巢","国家体育场")`` 默认值会污染任意其他对，已修）。
  4. **支持 1 keeper + N losers**：星型拓扑（S1/S2/S3 一组多别名）一次折完。

「全部信息」的可验证含义：
  - 任一原始行非空的列，合并后 keeper 不能为空；
  - JSON 数组列 = 所有行内容的并集（按内容去重、keeper 优先保序）；
  - 互补长文本列 = 所有行文本都在 keeper 里（拼接，带来源标记）；
  - 名字/英文名/别名全量并入 name_aliases（旧名仍可召回）；
  - 单值/标量冲突只留一个值，**被舍弃的值写进逐列台账 + DB 快照**，
    不制造半解析值。这是「一条有效记录」口径下的显式取舍。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Sequence


class Policy(str, Enum):
    """单列合并策略。"""

    IDENTITY = "identity"  # 身份/状态/坐标/更新戳：恒保留 keeper
    ARRAY = "array"  # JSON 数组：内容并集
    CONCAT = "concat"  # 互补事实长文本：两段(多段)都留
    TIMESTAMP = "timestamp"  # 核验时间戳：取较新
    PREFER_LONGER = "prefer_longer"  # 单值文本：取信息量更大者
    SCALAR = "scalar"  # 数值/枚举/布尔/外部 ID：冲突保留 keeper


# 源优先级（与 ops/scan_same_entity_pairs.py::_SOURCE_PRIORITY 同序）。
# 未在名单内的源（如 baidu）= 最低，index 越大越靠后。
SOURCE_PRIORITY: tuple[str, ...] = (
    "unesco",
    "5a",
    "museum1",
    "museum2",
    "museum3",
    "artmuseum",
    "street",
    "histown",
    "amap",
    "chinatravel",
    "osm",
)


# fmt: off
COLUMN_POLICIES: dict[str, Policy] = {
    # ---- identity（11 列）-------------------------------------------------
    **{c: Policy.IDENTITY for c in (
        "id", "source", "source_poi_id", "city", "name_zh", "category",
        "status", "location", "wgs84_location", "updated_at",
        "hours_updated_at",
    )},
    # ---- JSON 数组（6 列）------------------------------------------------
    **{c: Policy.ARRAY for c in (
        "tags", "photos", "name_aliases", "review_tags", "review_tags_en",
        "user_groups",
    )},
    # ---- 互补长文本（5 列）-----------------------------------------------
    **{c: Policy.CONCAT for c in (
        "intro", "intro_en", "review_summary", "review_summary_en",
        "ta_intro_en",
    )},
    # ---- 核验时间戳（3 列）-----------------------------------------------
    **{c: Policy.TIMESTAMP for c in (
        "photos_fetched_at", "ta_fetched_at", "access_updated_at",
    )},
    # ---- 单值文本：取更详（32 列）----------------------------------------
    **{c: Policy.PREFER_LONGER for c in (
        "name_en", "address", "address_en", "opening_hours",
        "opening_hours_en", "hours_source", "phone", "website",
        "rating_source", "tags_source", "intro_source", "photos_source",
        "best_visit_time", "best_visit_time_source", "review_tags_source",
        "ticket_source", "district", "business_area", "indoor", "rain_ok",
        "duration_source", "review_summary_source", "booking_url",
        "ta_url", "ta_opening_hours", "access_mode", "access_gateway",
        "access_note", "access_note_en", "access_source", "access_boarding",
        "user_family",
    )},
    # ---- 标量：冲突保留 keeper（21 列）-----------------------------------
    **{c: Policy.SCALAR for c in (
        "rating", "suggested_duration_min", "origin", "rating_count",
        "ticket_price_min", "ticket_price_max", "reservation_required",
        "reservation_advance_days", "photos_fetch_fail", "ta_location_id",
        "ta_geo_id", "ta_status", "ta_rating", "ta_suggested_duration_min",
        "access_minutes", "access_gateway_minutes", "access_boarding_lon",
        "access_boarding_lat", "access_service_minutes",
        "access_wait_minutes", "access_last_mile_minutes",
    )},
}
# fmt: on


class UnknownPoiColumnError(ValueError):
    """pois 出现策略表未覆盖的列：拒绝合并，避免静默丢信息。"""


@dataclass(frozen=True)
class ColumnCoverage:
    column_count: int
    unknown: tuple[str, ...] = ()
    stale: tuple[str, ...] = ()  # 策略表里有、DB 里没有（仅提示）


def assert_full_column_coverage(columns: Iterable[str]) -> ColumnCoverage:
    """动态列闸：DB 实际列必须全部有策略；未知列直接抛错。"""
    cols = list(columns)
    unknown = tuple(c for c in cols if c not in COLUMN_POLICIES)
    stale = tuple(c for c in COLUMN_POLICIES if c not in cols)
    if unknown:
        raise UnknownPoiColumnError(
            "pois 出现未覆盖列，拒绝全字段合并（先补 COLUMN_POLICIES）: "
            + ", ".join(unknown)
        )
    return ColumnCoverage(len(cols), unknown, stale)


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False


def json_key(value: Any) -> str:
    """数组并集的去重键（dict/标量统一序列化，sort_keys 保证稳定）。"""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return repr(value)


def union_values(*values: Any) -> list:
    """JSON 数组并集：按内容去重，首个非空行在前保序。"""
    out: list = []
    seen: set[str] = set()
    for group in values:
        for item in list(group or []):
            key = json_key(item)
            if key not in seen:
                seen.add(key)
                out.append(item)
    return out


def _brief(value: Any) -> str:
    """台账里被舍弃值的短表示（DB-free，避免把大对象塞进 receipt）。"""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, default=str)[:200]
    return str(value)[:200]


def column_concat_marker(source: str) -> str:
    return f"\n〔{source} 行并入〕"


def merge_column(
    col: str,
    keep: Any,
    lose: Any,
    *,
    loser_source: str = "",
    policy: Policy | None = None,
) -> tuple[Any, str, str]:
    """单列合并 → (merged_value, action, note)。纯函数。

    action ∈ identity / keep / fill / union / concat / newer /
              prefer_longer / keep_scalar。
    ``policy`` 省略时查 COLUMN_POLICIES；未知列抛 UnknownPoiColumnError。
    """
    pol = policy or COLUMN_POLICIES.get(col)
    if pol is None:
        raise UnknownPoiColumnError(f"列 {col} 不在 COLUMN_POLICIES 中")
    if pol is Policy.IDENTITY:
        return keep, "identity", ""
    if is_empty(lose):
        return keep, "keep", ""
    if is_empty(keep):
        return lose, "fill", "keeper 空 → 取退役行"
    if keep == lose:
        return keep, "keep", ""

    if pol is Policy.ARRAY:
        merged = union_values(keep, lose)
        if merged != keep:
            return merged, "union", f"并入 {len(merged) - len(keep or [])} 项"
        return keep, "keep", ""
    if pol is Policy.CONCAT:
        chunk = str(lose).strip()
        if chunk and chunk not in str(keep):
            merged = f"{keep}{column_concat_marker(loser_source)}{chunk}"
            return merged, "concat", "多行事实都留在 keeper"
        return keep, "keep", "退役行文本已含于 keeper"
    if pol is Policy.TIMESTAMP:
        try:
            if lose > keep:
                return lose, "newer", f"取较新 {lose} > {keep}"
        except TypeError:
            pass
        return keep, "keep", ""
    if pol is Policy.PREFER_LONGER:
        if len(str(lose)) > len(str(keep)):
            return (
                lose,
                "prefer_longer",
                (f"退役行更详（{len(str(lose))}>{len(str(keep))}）"),
            )
        return keep, "keep", ""
    # Policy.SCALAR：保留 keeper，退役行的值由逐列台账 + DB 快照留痕
    return keep, "keep_scalar", "标量冲突保留 keeper，退役行值留台账"


@dataclass(frozen=True)
class ColumnPlan:
    value: Any
    action: str  # 最终动作（history 为空则 keep）
    history: tuple[dict, ...] = ()  # 逐 loser 的处置留痕（台账用）


@dataclass
class FullMergePlan:
    """1 keeper + N losers 的全字段合并计划。"""

    columns: dict[str, ColumnPlan] = field(default_factory=dict)
    alias_union: list[str] = field(default_factory=list)
    loser_labels: tuple[str, ...] = ()
    column_count: int = 0
    # 标量冲突：值没变，但退役行被舍弃的值必须留痕（不算 changed_columns）
    conflicts: list[dict] = field(default_factory=list)

    @property
    def changed_columns(self) -> list[str]:
        return [c for c, p in self.columns.items() if p.history]


def _row_get(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


def build_alias_union(
    keeper_row: Any,
    loser_rows: Sequence[Any],
    extra: Sequence[str] = (),
) -> list[str]:
    """keeper + 所有 loser 的中英文名/别名全量并入 name_aliases。

    ``extra`` 默认空——调用方按具体地点传通行短名，不写死任何对象。
    """
    seeds: list[Any] = []
    for row in (keeper_row, *loser_rows):
        for key in ("name_zh", "name_en", "name_aliases"):
            value = _row_get(row, key)
            if isinstance(value, (list, tuple)):
                seeds.extend(value)
            elif value:
                seeds.append(value)
    seeds.extend(extra)
    keeper_name = str(_row_get(keeper_row, "name_zh") or "").strip()
    out: list[str] = []
    for seed in seeds:
        text = str(seed).strip()
        if text and text != keeper_name and text not in out:
            out.append(text)
    return out


def source_priority(source: str | None) -> int:
    try:
        return SOURCE_PRIORITY.index(source or "")
    except ValueError:
        return len(SOURCE_PRIORITY)


def completeness(row: Any, columns: Iterable[str] | None = None) -> int:
    """非空列数（keeper 自动选择用）。"""
    cols = list(columns) if columns is not None else list(COLUMN_POLICIES)
    return sum(1 for c in cols if not is_empty(_row_get(row, c)))


def choose_keeper(rows: Sequence[Any], keep_id: str | None = None) -> Any:
    """keeper 选择：显式 --keep 优先；否则 源优先级 > 完整度 > active > 新戳。

    源优先级是项目铁律（回源链可信度），完整度次之；与旧 merge_place 的
    ``_keeper_rank``（active > 完整度）不同，但本通道只处理人工过目的候选。
    """
    if keep_id:
        for row in rows:
            if str(_row_get(row, "id")) == str(keep_id):
                return row
        raise KeyError(f"--keep 指定的行不在组内: {keep_id}")
    if not rows:
        raise ValueError("空组")

    def rank(row: Any) -> tuple:
        updated = _row_get(row, "updated_at")
        return (
            1 if (_row_get(row, "status") or "active") == "active" else 0,
            -source_priority(_row_get(row, "source")),
            completeness(row),
            str(updated or ""),
        )

    return max(rows, key=rank)


def merge_rows(
    columns: Iterable[str],
    keeper_row: Any,
    loser_rows: Sequence[Any],
    *,
    extra_aliases: Sequence[str] = (),
    label_of: Any = None,
) -> FullMergePlan:
    """折出全字段合并计划（1 keeper + N losers），不碰 DB。"""
    cols = list(columns)
    coverage = assert_full_column_coverage(cols)
    labels = []
    for i, row in enumerate(loser_rows):
        if label_of is not None:
            labels.append(str(label_of(row, i)))
        else:
            src = _row_get(row, "source") or "?"
            name = _row_get(row, "name_zh") or str(_row_get(row, "id"))[:8]
            labels.append(f"{src}:{name}")

    current = {c: _row_get(keeper_row, c) for c in cols}
    histories: dict[str, list[dict]] = {c: [] for c in cols}
    conflicts: list[dict] = []
    for label, row in zip(labels, loser_rows):
        src = str(_row_get(row, "source") or label)
        for col in cols:
            before = current[col]
            loser_value = _row_get(row, col)
            new, action, note = merge_column(col, before, loser_value, loser_source=src)
            current[col] = new
            if action == "keep_scalar":
                # 标量冲突：值不变，只记被舍弃的一方（台账可追溯）
                conflicts.append(
                    {
                        "column": col,
                        "from": label,
                        "keeper_value": _brief(before),
                        "discarded_value": _brief(loser_value),
                    }
                )
            elif action not in ("identity", "keep"):
                histories[col].append({"from": label, "action": action, "note": note})

    plan = FullMergePlan(loser_labels=tuple(labels), conflicts=conflicts)
    for col in cols:
        hist = histories[col]
        last_action = hist[-1]["action"] if hist else "keep"
        plan.columns[col] = ColumnPlan(current[col], last_action, tuple(hist))
    plan.alias_union = build_alias_union(keeper_row, loser_rows, extra_aliases)
    plan.columns["name_aliases"] = ColumnPlan(
        plan.alias_union,
        "alias_union" if plan.alias_union else "keep",
        tuple(
            {"from": lbl, "action": "alias_union", "note": "名字/英文名变体并入"}
            for lbl in labels
        ),
    )
    plan.column_count = coverage.column_count
    return plan


def verify_plan(
    plan: FullMergePlan,
    keeper_after: Any,
    keeper_before: Any,
    loser_rows: Sequence[Any],
) -> list[str]:
    """纯函数复核：返回问题列表，空列表 = 合并结果符合「全部信息」口径。"""
    problems: list[str] = []
    cols = list(plan.columns)
    for col in cols:
        before_k = _row_get(keeper_before, col)
        got = _row_get(keeper_after, col)
        loser_vals = [_row_get(r, col) for r in loser_rows]
        if not is_empty(before_k) or any(not is_empty(v) for v in loser_vals):
            if is_empty(got):
                problems.append(f"{col}: 原始任一行非空，合并后为空")
        cp = plan.columns[col]
        for h in cp.history:
            if h["action"] == "union":
                for row in loser_rows:
                    for item in list(_row_get(row, col) or []):
                        if json_key(item) not in {json_key(x) for x in (got or [])}:
                            problems.append(f"{col}: 并集缺项 {json_key(item)[:60]}")
                            break
                break
            if h["action"] == "concat":
                for row in loser_rows:
                    text = str(_row_get(row, col) or "").strip()
                    if text and text not in str(got or ""):
                        problems.append(f"{col}: 退役行文本未保留")
                        break
                break
    for alias in plan.alias_union:
        if alias not in (_row_get(keeper_after, "name_aliases") or []):
            problems.append(f"name_aliases 缺 {alias}")
    return problems
