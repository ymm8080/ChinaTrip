"""参考数据单向同步核心（DESIGN language_dual_system §5.4，双语 P2）。

CN 生产 → 海外消费。本模块只放**纯逻辑**（可离线单测）：

  * export：ORM 行 → 可 JSON 化 dict（显式列白名单，坐标转 lon/lat，
    poi_hours 嵌套）；NDJSON 序列化 + manifest（SHA256/计数/水位）
  * import 决策：plan_import(record, existing) → insert/update/skip
    —— 幂等 upsert 语义：命中 (source, source_poi_id) 即按 CN 值覆盖
    业务列，但**本地 _en 译文列非空则保留**（译文资产区域私有，CN 值
    仅在本地为空时免费播种）；status 以 CN 为准（inactive 传播=墓碑）

DB 适配器在 app.jobs.export_reference / import_reference；weather 不走
本链（海外侧 Open-Meteo 全球可达，自取；详见设计文档修订 v1.2）。

约定：
  * 不导出 id——海外以自然键 (source, source_poi_id) 落库，本地生成 id；
    poi_hours 以父行自然键嵌套导出、导入时按本地 poi_id 重链
  * NDJSON 首行 = meta（schema 版本/导出时间/表版本），后续每行一条记录
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any

SCHEMA_VERSION = 1

# 显式白名单：pois 导出列（ORM 属性名；坐标与 hours 特殊处理）
POI_EXPORT_COLS: tuple[str, ...] = (
    "source",
    "source_poi_id",
    "city",
    "name_zh",
    "name_en",
    "category",
    "status",
    "address",
    "address_en",
    "intro",
    "intro_en",
    "phone",
    "website",
    "rating",
    "rating_source",
    "rating_count",
    "tags",
    "tags_source",
    "review_tags",
    "review_tags_source",
    "review_tags_en",
    "review_summary",
    "review_summary_en",
    "best_visit_time",
    "best_visit_time_source",
    "suggested_duration_min",
    "duration_source",
    "indoor",
    "rain_ok",
    "ticket_price_min",
    "ticket_price_max",
    "ticket_source",
    "opening_hours",
    "opening_hours_en",
    "hours_source",
    "reservation_required",
    "reservation_advance_days",
    "booking_url",
)  # P1.5：+review_summary/review_summary_en；P1.6：+opening_hours_en
RESTAURANT_EXPORT_COLS: tuple[str, ...] = (
    "source",
    "source_poi_id",
    "city",
    "name_zh",
    "name_en",
    "cuisine",
    "status",
    "address",
    "address_en",
    "intro",
    "intro_en",
    "phone",
    "website",
    "avg_cost",
    "rating",
    "rating_source",
    "tags",
    "tags_source",
    "review_tags",
    "review_tags_source",
    "review_tags_en",
    "cuisine",
    "cuisine_en",
    "signature_dishes",
    "signature_dishes_en",
    "meal_periods",
    "opening_hours",
    "opening_hours_en",
    "hours_source",
)  # P1.5：+review_tags_en/cuisine(_en)/signature_dishes(_en)；P1.6：+opening_hours_en
#: 本地译文列：import 覆盖时保留本地非空值
_EN_COLS = (
    "name_en",
    "intro_en",
    "address_en",
    "review_tags_en",
    "review_summary_en",
    "opening_hours_en",
    "cuisine_en",
    "signature_dishes_en",
)


def _jsonable(v: Any) -> Any:
    """Decimal/datetime/date → JSON 安全类型；其余原样。"""
    if v is None or isinstance(v, (str, int, float, bool, list, dict)):
        return v
    if isinstance(v, datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def row_to_record(
    table: str,
    row: Any,
    *,
    loc: tuple[float, float] | None = None,
    wgs84: tuple[float, float] | None = None,
    hours: list[dict] | None = None,
) -> dict:
    """ORM 行 → 导出 dict（列白名单 + 坐标 + 嵌套 hours）。"""
    cols = POI_EXPORT_COLS if table == "pois" else RESTAURANT_EXPORT_COLS
    rec: dict = {"table": table}
    for col in cols:
        rec[col] = _jsonable(getattr(row, col, None))
    if loc:
        rec["location"] = {"lon": loc[0], "lat": loc[1]}
    if wgs84:
        rec["wgs84_location"] = {"lon": wgs84[0], "lat": wgs84[1]}
    if table == "pois" and hours:
        rec["hours"] = [
            {"rule_type": h.get("rule_type"), "payload": h.get("payload")}
            for h in hours
        ]
    return rec


def serialize_export(records: list[dict], *, exported_at: str) -> tuple[str, dict]:
    """records → (NDJSON 文本, manifest)。manifest.sha256 覆盖除首行外全部行。"""
    meta = {"schema": SCHEMA_VERSION, "exported_at": exported_at}
    lines = [json.dumps(meta, ensure_ascii=False)]
    counts: dict[str, int] = {}
    for r in records:
        lines.append(json.dumps(r, ensure_ascii=False))
        counts[r["table"]] = counts.get(r["table"], 0) + 1
    ndjson = "\n".join(lines) + "\n"
    body = "\n".join(lines[1:]) + ("\n" if len(lines) > 1 else "")
    manifest = {
        "schema": SCHEMA_VERSION,
        "exported_at": exported_at,
        "counts": counts,
        "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }
    return ndjson, manifest


def verify_manifest(ndjson_text: str, manifest: dict) -> str | None:
    """校验正文哈希；不一致返回原因，一致返回 None。"""
    lines = ndjson_text.rstrip("\n").split("\n")
    body = "\n".join(lines[1:]) + ("\n" if len(lines) > 1 else "")
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    if digest != manifest.get("sha256"):
        return "sha256_mismatch"
    if int(lines[0] and json.loads(lines[0])["schema"]) != manifest.get("schema"):
        return "schema_mismatch"
    return None


def parse_export(ndjson_text: str) -> list[dict]:
    lines = ndjson_text.rstrip("\n").split("\n")
    return [json.loads(ln) for ln in lines[1:] if ln.strip()]


def plan_import(record: dict, existing: Any) -> tuple[str, dict]:
    """导入决策（纯函数）。

    返回 (action, updates)：
      insert  —— 本地无此自然键：全字段（含坐标/(_en)）写入
      update  —— 命中：业务列按 CN 值覆盖；本地 _en 非空保留、为空播种；
                 坐标 CN 有则覆盖
      skip    —— record 缺自然键等非法输入
    existing 为本地 ORM 行或 None；updates 的键为 ORM 属性名。
    """
    table = record.get("table")
    if not record.get("source") or not record.get("source_poi_id"):
        return ("skip", {})
    cols = POI_EXPORT_COLS if table == "pois" else RESTAURANT_EXPORT_COLS
    if existing is None:
        updates = {c: record.get(c) for c in cols}
        if record.get("location"):
            updates["location"] = (
                record["location"]["lon"],
                record["location"]["lat"],
            )
        if record.get("wgs84_location"):
            updates["wgs84_location"] = (
                record["wgs84_location"]["lon"],
                record["wgs84_location"]["lat"],
            )
        updates["origin"] = "cn_sync"
        return ("insert", updates)
    updates: dict = {}
    for c in cols:
        if c in _EN_COLS:
            local_en = getattr(existing, c, None)
            if local_en is None or local_en == "":
                updates[c] = record.get(c)  # 播种；本地已译则保留
            continue
        updates[c] = record.get(c)  # CN 为准（含 status 墓碑传播）
    if record.get("location"):
        updates["location"] = (
            record["location"]["lon"],
            record["location"]["lat"],
        )
    if record.get("wgs84_location"):
        updates["wgs84_location"] = (
            record["wgs84_location"]["lon"],
            record["wgs84_location"]["lat"],
        )
    return ("update", updates)
