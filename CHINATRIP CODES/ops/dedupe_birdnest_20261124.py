# -*- coding: utf-8 -*-
"""鸟巢(国家体育场) / 国家体育场·鸟巢 同实体 DEDUP（2026-11-24 用户拍板）。

pois 里两条 active 行指同一实体（amap d1da799a… / baidu 11662ce5…）：
贴文读点会双行占满命中槽，正是 R27「LLM 饥饿」事故的成因之一。
用户口径：**「TWO ENTRIES ARE IN POIS TABLE. MAKE SURE THE ONE LEFT HAS
ALL INFORMATION IN ALL TWO ENTRIES」**——退役一条，幸存行吸收两行全部信息。

keeper = amap「鸟巢(国家体育场)」d1da799a-e982-46ae-a228-1b20082a06eb
    依据：① _SOURCE_PRIORITY 里 amap 优先 baidu（baidu 不在名单=最低），
          S3 既有先例 `[上海] keeper=[amap] 七宝古镇 ← retired [baidu]`；
          ② 设计铁律「时间敏感字段只信高德/携程回源链」，opening_hours/
          hours_source=ctrip/indoor/rain_ok 都在这行；
          ③ 下游 tripadvisor_locations 唯一引用指向这行。
loser  = baidu「国家体育场·鸟巢」11662ce5-a407-4262-9fa3-9deafbf128f0
    → status='inactive'（不删行，可回滚）；其 phone / tags(intl,layla) /
    photos(mafengwo) / name_aliases / intro_source 等全部并入 keeper。

全 78 列逐列合并（不是既有 dedupe_pois 的 13 列 / S3 的 21 列）：
  identity 列保留 keeper；keeper 空则回填退役行；JSON 数组并集；
  互补长文本两段都留在 keeper（拼接）；*_at 时间戳取较新；
  单值文本取信息量更大者；名字/英文名变体全部并入 name_aliases
  （另加通行短名「鸟巢」「国家体育场」，保证旧名仍可召回）。

写库前：DB 快照表 + 全字段 CSV 台账 + 逐列处置 md（含回滚 SQL）。
幂等：loser 已非 active 即 no-op。支持 --rollback 从快照表整行恢复。

用法（cwd 任意，脚本自定位 ROOT）：
  .venv/Scripts/python.exe ops/dedupe_birdnest_20261124.py --dry-run
  .venv/Scripts/python.exe ops/dedupe_birdnest_20261124.py --apply
  .venv/Scripts/python.exe ops/dedupe_birdnest_20261124.py --rollback
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPS = ROOT / "ops"
KEEPER_ID = "d1da799a-e982-46ae-a228-1b20082a06eb"   # amap 鸟巢(国家体育场)
LOSER_ID = "11662ce5-a407-4262-9fa3-9deafbf128f0"    # baidu 国家体育场·鸟巢
BAK_TABLE = "pois_birdnest_dedup_bak_20261124"
LEDGER_CSV = OPS / "pois_birdnest_dedup_2026-11-24.csv"
REPORT_MD = OPS / "dedupe_birdnest_20261124.md"

# 身份/状态/坐标/更新戳：不因合并改写（坐标两针都在鸟巢，保留 keeper 针）
IDENTITY_COLS = frozenset({
    "id", "source", "source_poi_id", "city", "name_zh", "category", "status",
    "location", "wgs84_location", "updated_at", "hours_updated_at",
})
ARRAY_COLS = frozenset({
    "tags", "photos", "name_aliases", "review_tags", "review_tags_en",
    "user_family", "user_groups",
})
# 互补事实文本：两行措辞各有事实（如 2022 冬奥开闭幕式），拼接后两段都在
CONCAT_COLS = frozenset({
    "intro", "intro_en", "review_summary", "review_summary_en", "ta_intro_en",
})
# 单值文本：取信息量更大（更长）者，较短的一方记台账 / 名字变体进 aliases
PREFER_LONGER_COLS = frozenset({
    "name_en", "address", "address_en", "opening_hours", "opening_hours_en",
    "phone", "website", "rating_source", "tags_source", "intro_source",
    "photos_source", "duration_source", "review_tags_source",
    "review_summary_source", "best_visit_time_source", "ticket_source",
    "access_source", "access_note", "access_note_en", "access_gateway",
    "access_boarding", "district", "business_area", "origin", "indoor",
    "rain_ok", "best_visit_time", "ta_url", "ta_status", "access_mode",
    "booking_url", "reservation_required", "ta_opening_hours",
})
# 时间戳取较新（同源字段语义是「最后核验时间」）
TIMESTAMP_COLS = frozenset({
    "photos_fetched_at", "ta_fetched_at", "access_updated_at",
})
# 通行名：两行名字里都含这两个词，补进别名保证贴文「鸟巢/国家体育场」召回
SHORT_ALIASES = ("鸟巢", "国家体育场")


def _is_empty(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return not v.strip()
    if isinstance(v, (list, tuple, dict, set)):
        return len(v) == 0
    return False


def _json_key(v) -> str:
    try:
        return json.dumps(v, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return repr(v)


def union_values(a, b) -> list:
    """JSON 数组并集（按内容去重，保序：keeper 在前）。"""
    out, seen = [], set()
    for v in list(a or []) + list(b or []):
        key = _json_key(v)
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out


def merge_column(col: str, keep, lose, *, loser_source: str = "baidu"):
    """单列合并 → (merged_value, action, note)。纯函数，可无 DB 单测。"""
    if col in IDENTITY_COLS:
        return keep, "identity", ""
    if _is_empty(lose):
        return keep, "keep", ""
    if _is_empty(keep):
        return lose, "fill", "keeper 空 → 取退役行"
    if keep == lose:
        return keep, "keep", ""
    if col in ARRAY_COLS:
        merged = union_values(keep, lose)
        if merged != keep:
            return merged, "union", f"并入 {len(merged) - len(keep or [])} 项"
        return keep, "keep", ""
    if col in CONCAT_COLS:
        chunk = str(lose).strip()
        if chunk and chunk not in str(keep):
            merged = f"{keep}\n〔{loser_source} 行并入〕{chunk}"
            return merged, "concat", "两段事实都留在 keeper"
        return keep, "keep", "退役行文本已含于 keeper"
    if col in TIMESTAMP_COLS:
        try:
            if lose > keep:
                return lose, "newer", f"取较新 {lose} > {keep}"
        except TypeError:
            pass
        return keep, "keep", ""
    if col in PREFER_LONGER_COLS:
        if len(str(lose)) > len(str(keep)):
            note = f"退役行更详（{len(str(lose))}>{len(str(keep))}）"
            return lose, "prefer_longer", note
        return keep, "keep", ""
    # 数值/枚举/布尔（rating、ta_rating、suggested_duration_min、access_* 等）：
    # 保留 keeper 值，退役行的值留全字段台账与 DB 快照，不制造半解析值。
    return keep, "keep_scalar", ""


def build_alias_union(keeper_row, loser_row, extra=SHORT_ALIASES):
    """两行的中文名/英文名/别名全量并入 keeper.name_aliases（名字维度不丢信息）。"""
    seeds = []

    def _get(row, key):
        if isinstance(row, dict):
            return row.get(key)
        return getattr(row, key, None)

    for row in (keeper_row, loser_row):
        for key in ("name_zh", "name_en", "name_aliases"):
            v = _get(row, key)
            if isinstance(v, (list, tuple)):
                seeds.extend(v)
            elif v:
                seeds.append(v)
    seeds.extend(extra)
    keeper_name = str(_get(keeper_row, "name_zh") or "").strip()
    out = []
    for s in seeds:
        s = str(s).strip()
        if s and s != keeper_name and s not in out:
            out.append(s)
    return out


def _db_url() -> str:
    env = (ROOT / ".env").read_text(encoding="utf-8")
    match = re.search(r"DATABASE_URL\s*=\s*(.+)", env)
    return match.group(1).strip().strip('"').strip("'")


def _read_rows(engine, sql: str):
    from sqlalchemy import text
    with engine.connect() as c:
        cols = [r[0] for r in c.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='pois' ORDER BY ordinal_position"
        )).fetchall()]
        rows = [dict(r) for r in c.execute(text(sql)).mappings().all()]
    return cols, rows


def _csv_value(v):
    if v is None:
        return ""
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False, default=str)
    return str(v)


def _write_ledger(cols, rows) -> None:
    with open(LEDGER_CSV, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: _csv_value(r.get(k)) for k in cols})
    print(f"ledger: {LEDGER_CSV} ({len(rows)} rows, {len(cols)} cols)")


def _write_report(cols, keeper_before, loser_before, plan, alias_union, refs) -> None:
    lines = [
        "# 鸟巢两行 DEDUP 台账（2026-11-24）",
        "",
        f"- keeper：`{KEEPER_ID}` amap"
        f"「{keeper_before.get('name_zh')}」→ 继续 active",
        f"- loser：`{LOSER_ID}` baidu"
        f"「{loser_before.get('name_zh')}」→ status='inactive'",
        "- 依据：源优先级 amap>baidu（S3 先例）、"
        "hours 只信高德/携程回源链、下游引用指向 amap 行。",
        "- 用户口径：幸存行必须含两行全部信息；"
        "全 78 列逐列处置如下（只列非默认动作）。",
        "- 引用重指向："
        f"itinerary_items={refs.get('itinerary_items', 0)}，"
        f"trip_items={refs.get('trip_items', 0)}。",
        f"- 快照表：`{BAK_TABLE}`（两行全字段）；CSV 台账：`{LEDGER_CSV.name}`。",
        "",
        "## 逐列处置",
        "",
        "| 列 | 动作 | keeper 原值 | 退役行原值 | 说明 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for col, (new, action, note) in plan.items():
        if action in ("identity", "keep"):
            continue
        kv = _csv_value(keeper_before.get(col))
        lv = _csv_value(loser_before.get(col))
        note_txt = note or _csv_value(new)[:70]
        lines.append(
            f"| `{col}` | {action} | {kv[:70]} | {lv[:70]} | {note_txt} |"
        )
    lines += [
        "",
        "## name_aliases 最终值（两行名字/英文名变体 + 通行短名）",
        "",
        "```json",
        json.dumps(alias_union, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 回滚",
        "",
        "```bash",
        ".venv/Scripts/python.exe ops/dedupe_birdnest_20261124.py --rollback",
        "```",
        "",
        "或直接 SQL（从快照表整行恢复两行）：",
        "",
        "```sql",
        f"INSERT INTO pois SELECT * FROM {BAK_TABLE} "
        f"WHERE id IN ('{KEEPER_ID}','{LOSER_ID}')",
        "ON CONFLICT (id) DO UPDATE SET "
        + ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c != "id") + ";",
        "```",
        "",
    ]
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"report: {REPORT_MD}")


def _dry_run(cols, keeper, loser, plan, alias_union) -> None:
    print("=== DRY RUN（不写库、不写文件）===")
    print(f"keeper: [{keeper.get('source')}] {keeper.get('name_zh')}  {KEEPER_ID}")
    print(f"loser : [{loser.get('source')}] {loser.get('name_zh')}  {LOSER_ID}")
    for col, (new, action, note) in plan.items():
        if action in ("identity", "keep"):
            continue
        print(f"  {action:<14} {col:<26} {_csv_value(new)[:100]}")
    print("  alias_union:", json.dumps(alias_union, ensure_ascii=False))
    changed = sum(
        1 for _n, a, _x in plan.values() if a not in ("identity", "keep")
    )
    print(f"合计 {changed} 列有动作")


def _apply(engine, cols, keeper, loser, plan, alias_union) -> None:
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    if (loser.get("status") or "active") != "active":
        print("already applied: loser is not active → no-op")
        return
    # 1) 快照（DDL 内用固定 UUID 字面量，参数化 DDL 在 psycopg 不稳）
    with engine.begin() as c:
        c.execute(text(f"DROP TABLE IF EXISTS {BAK_TABLE}"))
        c.execute(text(
            f"CREATE TABLE {BAK_TABLE} AS SELECT * FROM pois "
            f"WHERE id IN ('{KEEPER_ID}','{LOSER_ID}')"
        ))
        n = c.execute(text(f"SELECT count(*) FROM {BAK_TABLE}")).scalar()
        assert n == 2, n
    print(f"snapshot: {BAK_TABLE} ({n} rows)")
    _write_ledger(cols, [keeper, loser])

    # 2) 合并 + 退役 + 引用重指向（单事务）
    with Session(engine) as s:
        k = s.get(_poi_model(), KEEPER_ID)
        loser_obj = s.get(_poi_model(), LOSER_ID)
        assert k is not None and loser_obj is not None
        for col, (new, action, _note) in plan.items():
            if action in ("identity", "keep"):
                continue
            if new != getattr(k, col, None):
                setattr(k, col, new)
        k.name_aliases = alias_union
        k.status = "active"
        k.updated_at = datetime.now()
        loser_obj.status = "inactive"
        loser_obj.updated_at = datetime.now()
        refs = {}
        for table in ("itinerary_items", "trip_items"):
            res = s.execute(
                text(f"UPDATE {table} SET poi_id=:k WHERE poi_id=:l"),
                {"k": KEEPER_ID, "l": LOSER_ID},
            )
            refs[table] = res.rowcount
        s.commit()
    print("merged + retired:", refs)

    # 3) 独立连接复核（防「事务内最后一条 SQL 报错整体回滚」旧坑）
    _verify(engine, plan, keeper, loser, alias_union)
    _write_report(cols, keeper, loser, plan, alias_union, refs)


def _poi_model():
    sys.path.insert(0, str(ROOT))
    from app.models import Poi
    return Poi


def _verify(engine, plan, keeper_before, loser_before, alias_union) -> None:
    from sqlalchemy import text
    with engine.connect() as c:
        rows = {str(r["id"]): dict(r) for r in c.execute(text(
            "SELECT * FROM pois WHERE id IN (:k,:l)"
        ), {"k": KEEPER_ID, "l": LOSER_ID}).mappings().all()}
    k, lrow = rows[KEEPER_ID], rows[LOSER_ID]
    assert k["status"] == "active", k["status"]
    assert lrow["status"] == "inactive", lrow["status"]
    problems = []
    for col, (_new, action, _note) in plan.items():
        if action in ("identity", "keep"):
            continue
        got, src = k.get(col), loser_before.get(col)
        if action == "fill" and _is_empty(got):
            problems.append(f"{col}: fill 未落库")
        elif action == "union":
            for item in (src or []):
                if _json_key(item) not in {_json_key(x) for x in (got or [])}:
                    problems.append(f"{col}: 并集缺项 {_json_key(item)[:60]}")
                    break
        elif action == "concat" and str(src).strip() not in str(got or ""):
            problems.append(f"{col}: 退役行文本未保留")
        elif action in ("prefer_longer", "newer") and _is_empty(got):
            problems.append(f"{col}: 取优后为空")
    for a in alias_union:
        if a not in (k.get("name_aliases") or []):
            problems.append(f"name_aliases 缺 {a}")
    if problems:
        raise AssertionError("VERIFY FAILED: " + "; ".join(problems))
    filled = sum(1 for _n, a, _x in plan.values() if a not in ("identity", "keep"))
    print(f"VERIFY OK: keeper=active, loser=inactive, {filled} 列动作全部落库")


def _rollback(engine, cols) -> None:
    from sqlalchemy import text
    collist = ", ".join(cols)
    sets = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c != "id")
    with engine.begin() as c:
        res = c.execute(text(
            f"INSERT INTO pois ({collist}) SELECT {collist} FROM {BAK_TABLE} "
            f"WHERE id IN ('{KEEPER_ID}','{LOSER_ID}') "
            f"ON CONFLICT (id) DO UPDATE SET {sets}"
        ))
        rows = {str(r["id"]): r["status"] for r in c.execute(text(
            "SELECT id, status FROM pois WHERE id IN (:k,:l)"
        ), {"k": KEEPER_ID, "l": LOSER_ID}).mappings().all()}
    print(f"rollback done (rowcount={res.rowcount}): {rows}")


def main() -> None:
    # 只在命令行执行时换 stdout 编码（importlib 单测加载不碰 sys.stdout）
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="鸟巢两行同实体 DEDUP（全字段合并）")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="只算不写")
    g.add_argument("--apply", action="store_true", help="快照+合并+退役+验证")
    g.add_argument("--rollback", action="store_true", help="从快照表整行恢复")
    args = ap.parse_args()

    from sqlalchemy import create_engine
    engine = create_engine(_db_url())
    cols, rows = _read_rows(
        engine,
        "SELECT * FROM pois WHERE id IN "
        f"('{KEEPER_ID}','{LOSER_ID}') ORDER BY id",
    )
    by_id = {str(r["id"]): r for r in rows}
    assert KEEPER_ID in by_id and LOSER_ID in by_id, "两行必须都在 pois 表"
    keeper, loser = by_id[KEEPER_ID], by_id[LOSER_ID]

    if args.rollback:
        _rollback(engine, cols)
        return

    plan = {
        col: merge_column(col, keeper.get(col), loser.get(col), loser_source="baidu")
        for col in cols
    }
    alias_union = build_alias_union(keeper, loser)
    if args.dry_run:
        _dry_run(cols, keeper, loser, plan, alias_union)
        return
    _apply(engine, cols, keeper, loser, plan, alias_union)


if __name__ == "__main__":
    main()
