# -*- coding: utf-8 -*-
"""POI 去重作业：一条有效记录，其余 inactive。

两条通道，**旧通道完全保留**（默认行为不变）：

  A. 传统 ``merge_place``（约 14 列、只填空、同地名内核判定）
    # 看某个地方会怎么合并（只算不写）
    python -m app.jobs.dedupe_pois --city 上海 --name 朱家角 --dry-run
    # 真合并（默认把信息最全的 active 行当幸存者）
    python -m app.jobs.dedupe_pois --city 上海 --name 朱家角 --apply
    # 指定幸存行（source:source_poi_id 或 UUID）
    python -m app.jobs.dedupe_pois --city 上海 --name 朱家角 --keep 4a:4a_0064 --apply
    # 扫全城（默认 dry-run；--apply 才写库）
    python -m app.jobs.dedupe_pois --city 上海 --scan --limit 200 --apply

  B. **全字段合并**（2026-11-24 用户口径「幸存行必须含全部行的信息」）
    逐列处置 pois 全 78 列：空值回填 / 数组并集 / 互补文本拼接 /
    时间戳取新 / 单值取详 / 标量冲突留台账；名字变体全并入 name_aliases；
    **所有**含 poi_id 的下游表引用重指向 keeper；写库前批次快照 + 逐列台账。

    # 显式指定一对（UUID 或 source:source_poi_id），1 keeper + N losers
    python -m app.jobs.dedupe_pois --city 北京 \
        --pair '<keeper>|<loser1>,<loser2>' --dry-run
    python -m app.jobs.dedupe_pois --pair '<keeper>|<loser>' --apply
    # 对某个名字/扫全城也用全字段引擎
    python -m app.jobs.dedupe_pois --city 上海 --name 朱家角 --full --dry-run
    python -m app.jobs.dedupe_pois --city 上海 --scan --full --dry-run
    # 跨名同实体候选扫描（只列不写；人工过目后用 --pair 指定 keeper/loser）
    python -m app.jobs.dedupe_pois --scan-aliases --city 北京 --min-shared 4
    # 按批次整行回滚
    python -m app.jobs.dedupe_pois --rollback-batch full_20261124_080000_ab12cd34

安全约束：
  - 全字段通道默认 dry-run；写库必须显式 --apply。
  - 跨名候选扫描**永不写库**（--apply 直接报错），候选要人工拍板。
  - 动态列闸：information_schema 里每个 pois 列都必须在策略表中，
    否则 ``UnknownPoiColumnError`` 拒绝执行（防 schema 漂移静默丢信息）。
  - 批次快照表只增不删（不像一次性脚本 DROP TABLE），多次/多对可共存。
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db import get_session_factory
from app.models import Poi
from app.services.poi_ingest import merge_place
from app.services.poi_merge_full import (
    UnknownPoiColumnError,
    assert_full_column_coverage,
    choose_keeper,
    merge_rows,
    verify_plan,
)
from app.services.poi_names import place_core

_BACKUP_DIR = Path(__file__).resolve().parents[3] / "DESIGN" / "backup"
_BAK_TABLE = "pois_full_dedup_bak"


# ---------------------------------------------------------------- 旧通道辅助
def _resolve_keep(keep: str, factory) -> str | None:
    """``--keep`` 支持 UUID 或 ``source:source_poi_id``（目录源口味更自然）。"""
    if ":" not in keep:
        return keep
    source, source_poi_id = keep.split(":", 1)
    with factory() as session:
        row = (
            session.query(Poi.id)
            .filter(Poi.source == source, Poi.source_poi_id == source_poi_id)
            .first()
        )
    return str(row[0]) if row is not None else None


def _scan_candidates(city: str | None, limit: int) -> list[str]:
    """同城同内核、多于一条 active 行的地名（扫全城用）。"""
    sql = (
        "SELECT name_zh, city, count(*) AS n FROM pois"
        " WHERE (status IS NULL OR status = 'active')"
    )
    params: dict = {}
    if city:
        sql += " AND city = ANY(:cities)"
        params["cities"] = [city, f"{city}市"]
    sql += " GROUP BY name_zh, city HAVING count(*) > 1"
    factory = get_session_factory()
    with factory() as session:
        rows = session.execute(text(sql), params).all()
    buckets: dict[tuple[str, str], list[str]] = {}
    for name, row_city, _n in rows:
        core = place_core(name)
        if core:
            buckets.setdefault((str(row_city), core), []).append(str(name))
    out: list[str] = []
    for (_row_city, _core), names in buckets.items():
        out.append(names[0])
    return out[:limit]


# ---------------------------------------------------------------- 全字段公共件
def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def _in_clause(prefix: str, values: list[str]) -> tuple[str, dict]:
    params = {f"{prefix}{i}": v for i, v in enumerate(values)}
    clause = ", ".join(f":{k}" for k in params)
    return clause, params


def _db_url() -> str:
    root = Path(__file__).resolve().parents[2]
    env = (root / ".env").read_text(encoding="utf-8")
    match = re.search(r"DATABASE_URL\s*=\s*(.+)", env)
    return match.group(1).strip().strip('"').strip("'")


def _engine():
    return create_engine(_db_url())


def _pois_columns(conn) -> list[str]:
    return [
        r[0]
        for r in conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='pois' AND table_schema='public' "
            "ORDER BY ordinal_position"
        )).fetchall()
    ]


def _load_rows(conn, cols: list[str], ids: list[str]) -> dict[str, dict]:
    clause, params = _in_clause("id", ids)
    rows = conn.execute(
        text(f"SELECT * FROM pois WHERE id::text IN ({clause})"), params
    ).mappings().all()
    return {str(r["id"]): dict(r) for r in rows}


def _resolve_id(conn, token: str) -> str:
    """UUID 或 ``source:source_poi_id`` → pois.id（字符串）。"""
    token = token.strip()
    if ":" not in token:
        return token
    source, source_poi_id = token.split(":", 1)
    row = conn.execute(
        text("SELECT id FROM pois WHERE source=:s AND source_poi_id=:p"),
        {"s": source, "p": source_poi_id},
    ).first()
    if row is None:
        raise KeyError(f"找不到 POI: {token}")
    return str(row[0])


def _rows_by_name(conn, city: str | None, name: str) -> list[str]:
    sql = (
        "SELECT id::text FROM pois WHERE name_zh=:n "
        "AND (status IS NULL OR status='active')"
    )
    params: dict = {"n": name}
    if city:
        sql += " AND city IN (:c1, :c2)"
        params.update(c1=city, c2=f"{city}市")
    return [r[0] for r in conn.execute(text(sql), params).fetchall()]


def _ref_tables(conn) -> list[tuple[str, bool]]:
    """所有含 poi_id 的下游表 + 该列是否有唯一约束（PK/UNIQUE）。"""
    tables = [
        r[0]
        for r in conn.execute(text(
            "SELECT table_name FROM information_schema.columns "
            "WHERE column_name='poi_id' AND table_schema='public' "
            "AND table_name <> :bak ORDER BY table_name"
        ), {"bak": _BAK_TABLE}).fetchall()
    ]
    out = []
    for table in tables:
        unique = conn.execute(text(
            "SELECT count(*) FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON tc.constraint_name=kcu.constraint_name "
            "WHERE tc.table_schema='public' AND tc.table_name=:t "
            "  AND tc.constraint_type IN ('PRIMARY KEY','UNIQUE') "
            "  AND kcu.column_name='poi_id'"
        ), {"t": table}).scalar()
        out.append((table, bool(unique)))
    return out


def _ref_counts(conn, tables, ids: list[str]) -> dict[str, int]:
    clause, params = _in_clause("r", ids)
    out = {}
    for table, _unique in tables:
        out[table] = conn.execute(
            text(f"SELECT count(*) FROM {_q(table)} WHERE poi_id::text IN ({clause})"),
            params,
        ).scalar()
    return out


# ---------------------------------------------------------------- 跨名候选扫描
def _longest_common_substring(a: str, b: str) -> str:
    """中英文数字去标点后的最长公共子串（跨名同实体的弱信号）。"""
    clean_a = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", a or "")
    clean_b = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", b or "")
    best = ""
    for i in range(len(clean_a)):
        for j in range(i + len(best) + 1, len(clean_a) + 1):
            if clean_a[i:j] in clean_b:
                best = clean_a[i:j]
            else:
                break
    return best


def _scan_alias_candidates(
    conn, city: str | None, max_meters: float, min_shared: int, limit: int
) -> list[dict]:
    """跨名同实体候选：同城 + 坐标近 + place_core 不同 + 名称最长公共子串够长。

    只列不写（候选含真重复与「千岛湖XX / 千岛湖YY」这类同片区不同点），
    按项目 S3 惯例逐对人工过目后再用 --pair 拍板。
    """
    sql = (
        "SELECT a.id::text AS aid, b.id::text AS bid, a.name_zh AS an, "
        "b.name_zh AS bn, a.source AS asrc, b.source AS bsrc, a.city AS city, "
        "round(ST_Distance(a.location,b.location)::numeric,1) AS d_m, "
        "a.category AS ac, b.category AS bc "
        "FROM pois a JOIN pois b ON a.id < b.id "
        "WHERE (a.status IS NULL OR a.status='active') "
        "  AND (b.status IS NULL OR b.status='active') "
        "  AND a.city=b.city AND a.name_zh<>b.name_zh "
        "  AND a.name_zh IS NOT NULL AND b.name_zh IS NOT NULL "
        "  AND a.location IS NOT NULL AND b.location IS NOT NULL "
        "  AND ST_DWithin(a.location, b.location, :meters) "
        "  AND COALESCE(a.category,'') NOT IN ('hotel','food','transport','service') "
        "  AND COALESCE(b.category,'') NOT IN ('hotel','food','transport','service')"
    )
    params: dict = {"meters": max_meters}
    if city:
        sql += " AND a.city IN (:c1, :c2)"
        params.update(c1=city, c2=f"{city}市")
    rows = conn.execute(text(sql), params).mappings().all()
    out: list[dict] = []
    for r in rows:
        if place_core(r["an"]) == place_core(r["bn"]):
            continue  # 旧通道已能发现
        shared = _longest_common_substring(r["an"], r["bn"])
        if len(shared) < min_shared:
            continue
        out.append({
            "distance_m": float(r["d_m"]), "shared": shared,
            "keeper_hint": None, "a": dict(r),
        })
    out.sort(key=lambda x: (-len(x["shared"]), x["distance_m"]))
    return out[:limit]


# ---------------------------------------------------------------- 快照 / 回滚
def _ensure_backup_table(conn, cols: list[str]) -> None:
    exists = conn.execute(
        text("SELECT to_regclass('public." + _BAK_TABLE + "')")
    ).scalar()
    if not exists:
        collist = ", ".join(_q(c) for c in cols)
        conn.execute(text(
            f"CREATE TABLE {_q(_BAK_TABLE)} AS "
            f"SELECT {collist} FROM pois WHERE false"
        ))
        conn.execute(text(
            f"ALTER TABLE {_q(_BAK_TABLE)} "
            "ADD COLUMN batch_id text NOT NULL, "
            "ADD COLUMN dedup_at timestamptz NOT NULL DEFAULT now()"
        ))
        return
    bak_cols = {
        r[0]
        for r in conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name=:t AND table_schema='public'"
        ), {"t": _BAK_TABLE}).fetchall()
    }
    missing = [c for c in (*cols, "batch_id", "dedup_at") if c not in bak_cols]
    if missing:
        raise RuntimeError(
            f"快照表 {_BAK_TABLE} 已存在但缺列 {missing}；请人工处理，"
            "本作业不会 DROP 已有快照（防止毁掉历史回滚点）"
        )


def _snapshot(conn, cols: list[str], ids: list[str], batch_id: str) -> int:
    clause, params = _in_clause("s", ids)
    params["batch"] = batch_id
    collist = ", ".join(_q(c) for c in cols)
    res = conn.execute(text(
        f"INSERT INTO {_q(_BAK_TABLE)} ({collist}, batch_id) "
        f"SELECT {collist}, :batch FROM pois WHERE id::text IN ({clause})"
    ), params)
    return res.rowcount


def _rollback_batch(conn, cols: list[str], batch_id: str) -> dict:
    exists = conn.execute(
        text("SELECT to_regclass('public." + _BAK_TABLE + "')")
    ).scalar()
    if not exists:
        raise RuntimeError(f"快照表 {_BAK_TABLE} 不存在，无法回滚")
    ids = [
        r[0]
        for r in conn.execute(
            text(f"SELECT id::text FROM {_q(_BAK_TABLE)} WHERE batch_id=:b"),
            {"b": batch_id},
        ).fetchall()
    ]
    if not ids:
        raise RuntimeError(f"批次 {batch_id} 无快照行")
    clause, params = _in_clause("r", ids)
    params["b"] = batch_id
    collist = ", ".join(_q(c) for c in cols)
    sets = ", ".join(
        f"{_q(c)}=EXCLUDED.{_q(c)}" for c in cols if c != "id"
    )
    res = conn.execute(text(
        f"INSERT INTO pois ({collist}) "
        f"SELECT {collist} FROM {_q(_BAK_TABLE)} "
        f"WHERE batch_id=:b AND id::text IN ({clause}) "
        f"ON CONFLICT (id) DO UPDATE SET {sets}"
    ), params)
    statuses = {
        str(r["id"]): r["status"]
        for r in conn.execute(
            text(f"SELECT id, status FROM pois WHERE id::text IN ({clause})"),
            {k: v for k, v in params.items() if k.startswith("r")},
        ).mappings().all()
    }
    return {"batch_id": batch_id, "rowcount": res.rowcount, "statuses": statuses}


# ---------------------------------------------------------------- 写库 / 验证
def _retarget(conn_or_session, tables, keeper_id: str, loser_ids: list[str]) -> dict:
    clause, params = _in_clause("l", loser_ids)
    params["k"] = keeper_id
    out: dict[str, dict] = {}
    for table, is_unique in tables:
        if is_unique:
            n_keeper = conn_or_session.execute(
                text(
                    f"SELECT count(*) FROM {_q(table)} "
                    "WHERE poi_id = CAST(:k AS uuid)"
                ),
                {"k": keeper_id},
            ).scalar()
            n_loser = conn_or_session.execute(
                text(
                    f"SELECT count(*) FROM {_q(table)} "
                    f"WHERE poi_id::text IN ({clause})"
                ),
                {k: v for k, v in params.items() if k.startswith("l")},
            ).scalar()
            if n_loser and n_keeper:
                out[table] = {
                    "updated": 0,
                    "skipped": f"poi_id 唯一且 keeper 已有 {n_keeper} 行；"
                               f"loser 的 {n_loser} 行保留不删（需人工并表）",
                }
                continue
        res = conn_or_session.execute(text(
            f"UPDATE {_q(table)} SET poi_id = CAST(:k AS uuid) "
            f"WHERE poi_id::text IN ({clause})"
        ), params)
        out[table] = {"updated": res.rowcount}
    return out


def _apply_full(engine, cols, keeper_id, loser_ids, plan, *, city, batch_id) -> dict:
    all_ids = [keeper_id, *loser_ids]
    with engine.begin() as conn:
        _ensure_backup_table(conn, cols)
        snapped = _snapshot(conn, cols, all_ids, batch_id)
        assert snapped == len(all_ids), (snapped, len(all_ids))
    with Session(engine) as session:
        keeper = session.get(Poi, keeper_id)
        losers = [session.get(Poi, i) for i in loser_ids]
        assert keeper is not None and all(row is not None for row in losers)
        for col in plan.changed_columns:
            setattr(keeper, col, plan.columns[col].value)
        keeper.name_aliases = plan.alias_union
        keeper.status = "active"
        keeper.updated_at = datetime.now()
        for loser in losers:
            loser.status = "inactive"
            loser.updated_at = datetime.now()
        refs = _retarget(session, _ref_tables(session), keeper_id, loser_ids)
        session.commit()
    return {"snapshot_rows": snapped, "refs": refs}


def _verify_full(engine, cols, keeper_id, loser_ids, plan, keeper_before,
                 loser_rows, refs) -> None:
    with engine.connect() as conn:
        now = _load_rows(conn, cols, [keeper_id, *loser_ids])
        tables = _ref_tables(conn)
        remaining = _ref_counts(conn, tables, loser_ids)
    keeper_after, before = now[keeper_id], keeper_before
    if (keeper_after.get("status") or "active") != "active":
        raise AssertionError("keeper 不是 active")
    for i in loser_ids:
        if (now[i].get("status") or "active") == "active":
            raise AssertionError(f"loser {i} 仍是 active")
    problems = verify_plan(plan, keeper_after, before, loser_rows)
    for table, n in remaining.items():
        skipped = "skipped" in (refs.get(table) or {})
        if n and not skipped:
            problems.append(f"{table}: 仍有 {n} 条引用指向退役行")
    if problems:
        raise AssertionError("VERIFY FAILED: " + "; ".join(problems))


def _csv_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def _write_ledger(cols, rows, plan, batch_id, refs, *, city, applied) -> Path:
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = _BACKUP_DIR / f"poi_dedupe_full_{batch_id}.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: _csv_value(row.get(c)) for c in cols})
    actions = []
    for col in plan.changed_columns:
        cp = plan.columns[col]
        actions.append({
            "column": col, "final_action": cp.action,
            "final_value": _csv_value(cp.value)[:200],
            "history": list(cp.history),
        })
    receipt = {
        "batch_id": batch_id,
        "applied": applied,
        "city": city,
        "column_count": plan.column_count,
        "keeper": {"id": rows[0].get("id"), "name_zh": rows[0].get("name_zh"),
                   "source": rows[0].get("source")},
        "losers": [
            {"id": r.get("id"), "name_zh": r.get("name_zh"),
             "source": r.get("source")}
            for r in rows[1:]
        ],
        "changed_columns": plan.changed_columns,
        "actions": actions,
        "conflicts": plan.conflicts,  # 标量冲突：keeper 值保留，退役行值留痕
        "alias_union": plan.alias_union,
        "refs": refs,
        "snapshot": {"table": _BAK_TABLE, "batch_id": batch_id},
        "original_rows_csv": csv_path.name,
        "rollback": f"python -m app.jobs.dedupe_pois --rollback-batch {batch_id}",
    }
    json_path = _BACKUP_DIR / f"poi_dedupe_full_{batch_id}.json"
    json_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return json_path


# ---------------------------------------------------------------- 全字段主流程
def _run_full(args, engine) -> None:
    if args.rollback_batch:
        # 写事务单独开：engine.connect() 的隐式事务不会自动提交 DML
        with engine.begin() as wconn:
            cols = _pois_columns(wconn)
            result = _rollback_batch(wconn, cols, args.rollback_batch)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return

    with engine.connect() as conn:
        cols = _pois_columns(conn)
        coverage = assert_full_column_coverage(cols)  # 动态列闸：未知列即拒绝
        if coverage.stale:
            logging.warning("策略表含 DB 已无的列（仅提示）: %s", coverage.stale)
        tables = _ref_tables(conn)

        if args.scan_aliases:
            if args.apply:
                raise SystemExit("跨名候选扫描只列不写；请人工过目后用 --pair 指定")
            hits = _scan_alias_candidates(
                conn, args.city, args.max_meters, args.min_shared, args.limit
            )
            print(f"=== 跨名同实体候选（{len(hits)} 对，只列不写）===")
            for h in hits:
                r = h["a"]
                print(
                    f"  {h['distance_m']:>6.1f}m  LCS={h['shared']:<8} "
                    f"{r['an'][:24]:<24} [{r['asrc']}]  |  "
                    f"{r['bn'][:24]:<24} [{r['bsrc']}]  "
                    f"--pair '{r['aid']}|{r['bid']}'"
                )
            print(
                f"\n（候选 {len(hits)} 对；人工拍板后用 "
                "--pair <keeper>|<loser> --apply）"
            )
            return

        # 组内 id 解析
        if args.pair:
            if "|" not in args.pair:
                raise SystemExit("--pair 格式：'<keeper>|<loser1>,<loser2>'")
            k_token, l_token = args.pair.split("|", 1)
            keeper_id = _resolve_id(conn, k_token)
            loser_ids = [_resolve_id(conn, t) for t in l_token.split(",") if t.strip()]
            if not loser_ids or keeper_id in loser_ids:
                raise SystemExit("--pair 需要至少一个独立 loser")
            rows_map = _load_rows(conn, cols, [keeper_id, *loser_ids])
        else:
            names = (
                [args.name] if args.name
                else _scan_candidates(args.city, args.limit)
            )
            if not names:
                print("无可处理地名")
                return
            # 多地名时逐个处理（沿用旧通道的 receipts 语义）
            for name in names:
                ids = _rows_by_name(conn, args.city, name)
                if len(ids) < 2:
                    print(f"· {name}: 无同地名重复行（active {len(ids)} 条）")
                    continue
                rows = _load_rows(conn, cols, ids)
                keep_id = (
                    _resolve_keep(args.keep, get_session_factory())
                    if args.keep else None
                )
                keeper_row = choose_keeper([rows[i] for i in ids], keep_id)
                keeper_id = str(keeper_row["id"])
                loser_ids = [i for i in ids if i != keeper_id]
                rows_map = {i: rows[i] for i in [keeper_id, *loser_ids]}
                _run_one_full(
                    args, engine, conn, cols, tables, keeper_id, loser_ids,
                    rows_map, name,
                )
            return
        _run_one_full(
            args, engine, conn, cols, tables, keeper_id, loser_ids,
            rows_map,
            args.city or str(rows_map[keeper_id].get("name_zh") or "pair"),
        )


def _run_one_full(args, engine, conn, cols, tables, keeper_id, loser_ids,
                  rows_map, label) -> None:
    keeper = rows_map[keeper_id]
    losers = [rows_map[i] for i in loser_ids]
    inactive = [
        str(r.get("name_zh"))
        for r in losers
        if (r.get("status") or "active") != "active"
    ]
    if inactive:
        print(f"· {label}: already applied（loser 已非 active: {inactive}）→ no-op")
        return
    plan = merge_rows(cols, keeper, losers)
    batch_id = f"full_{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex[:8]}"
    refs_preview = _ref_counts(conn, tables, loser_ids)
    print(f"=== 全字段合并计划 [{label}] ===  {len(cols)} 列逐列处置")
    print(f"keeper : [{keeper.get('source')}] {keeper.get('name_zh')}  {keeper_id}")
    for row in losers:
        print(f"loser  : [{row.get('source')}] {row.get('name_zh')}  {row.get('id')}")
    print(f"changed: {len(plan.changed_columns)} 列  |  batch: {batch_id}")
    for col in plan.changed_columns:
        cp = plan.columns[col]
        print(f"  {cp.action:<14} {col:<26} {_csv_value(cp.value)[:110]}")
    print("  alias_union:", json.dumps(plan.alias_union, ensure_ascii=False))
    print("  下游引用(退役行):", json.dumps(refs_preview, ensure_ascii=False))
    if not args.apply:
        print("（dry-run：不写库、不写文件、不建快照表；加 --apply 执行）")
        return
    result = _apply_full(
        engine, cols, keeper_id, loser_ids, plan, city=label, batch_id=batch_id
    )
    _verify_full(
        engine, cols, keeper_id, loser_ids, plan, keeper, losers,
        result["refs"],
    )
    path = _write_ledger(
        cols, [keeper, *losers], plan, batch_id, result["refs"],
        city=label, applied=True,
    )
    print(f"APPLIED + VERIFY OK; snapshot={_BAK_TABLE}/{batch_id}; ledger={path}")


# ---------------------------------------------------------------- CLI
def main() -> None:
    parser = argparse.ArgumentParser(
        description="POI 去重（一条有效，其余 inactive；--full 走全字段合并）"
    )
    parser.add_argument("--city", default=None, help="城市（如 上海）")
    parser.add_argument("--name", default=None, help="地点名/内核（如 朱家角）")
    parser.add_argument(
        "--keep", default=None, help="指定幸存行（source:source_poi_id 或 UUID）"
    )
    parser.add_argument("--scan", action="store_true", help="扫全城同内核多行地点")
    parser.add_argument("--limit", type=int, default=200, help="扫描上限")
    parser.add_argument("--apply", action="store_true", help="真写库（缺省只算不写）")
    parser.add_argument(
        "--dry-run", action="store_true", help="只算不写（缺省行为，显式开关为可读性）"
    )
    parser.add_argument("--verbose", action="store_true")
    # ---- 全字段通道 ----
    parser.add_argument(
        "--full", action="store_true",
        help="用全字段合并引擎（默认仍走 merge_place 旧通道）",
    )
    parser.add_argument(
        "--pair", default=None,
        help="显式同实体组 '<keeper>|<loser1>,<loser2>'，隐含 --full",
    )
    parser.add_argument(
        "--scan-aliases", action="store_true",
        help="跨名同实体候选扫描（只列不写，隐含 dry-run）",
    )
    parser.add_argument(
        "--max-meters", type=float, default=100.0, help="候选扫描最大坐标距离（米）"
    )
    parser.add_argument(
        "--min-shared", type=int, default=4, help="候选扫描名称最长公共子串最小长度"
    )
    parser.add_argument(
        "--rollback-batch", default=None, help="按批次从快照表整行恢复"
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    full_channel = bool(
        args.full or args.pair or args.scan_aliases or args.rollback_batch
    )
    if full_channel:
        if not (args.pair or args.scan_aliases or args.rollback_batch
                or args.name or args.scan):
            parser.error(
                "全字段通道需要 --pair / --scan-aliases / --name / "
                "--scan / --rollback-batch"
            )
        try:
            _run_full(args, _engine())
        except UnknownPoiColumnError as exc:
            raise SystemExit(f"动态列闸拒绝执行：{exc}") from exc
        return

    # ---------------- 旧通道（原样保留） ----------------
    if not args.name and not args.scan:
        parser.error("需要 --name 或 --scan")
    names = [args.name] if args.name else _scan_candidates(args.city, args.limit)
    factory = get_session_factory()
    receipts: list[dict] = []
    merged = 0
    for name in names:
        result = merge_place(
            name,
            args.city,
            factory=factory,
            dry_run=not args.apply,
            keep_id=_resolve_keep(args.keep, factory) if args.keep else None,
        )
        if result is None:
            print(f"· {name}: 无同地名重复行")
            continue
        merged += 1
        payload = result.as_dict()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        if args.apply:
            receipts.append({"query": name, "city": args.city, **payload})
    if not args.apply:
        print(f"\n（dry-run）可合并 {merged} 处；加 --apply 写库")
        return
    if receipts:
        _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        path = _BACKUP_DIR / f"poi_dedupe_{date.today().isoformat()}.json"
        path.write_text(
            json.dumps(receipts, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"已写库 {merged} 处；快照 {path}")


if __name__ == "__main__":
    main()
