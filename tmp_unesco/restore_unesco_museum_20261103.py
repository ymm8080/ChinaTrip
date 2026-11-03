# -*- coding: utf-8 -*-
r"""UNESCO 刷新 + museum 四源恢复（2026-11-03，数据侧会话）。

①大足石刻/秦始皇陵：从 ops/pois_inactive_purge_backup_2026-11-03.csv 恢复
  （§4 正典词表不命中=误删；status inactive→active，city/坐标/name_en 随备份）。
②新疆天山：旧库(PG18:5433) unesco_whc_1414 泛名行原样迁入（city=''，
  对齐「泛名行维持归档」拍板；组件补核另立项）。
③峨眉山—乐山大佛(whc 779)/梵净山(whc 1559)：本征缺口新建，
  source_poi_id=unesco_whc_<ref> 惯例（同新疆天山行）。
④museum1/museum2/museum3/artmuseum 871 行旧库→活库（全 active，
  ON CONFLICT (source,source_poi_id) DO NOTHING 幂等）。

数据文件 tmp_unesco/museum_restore.csv 由 WSL 侧 psql \copy 生成
（geometry 走 ST_AsText，本脚本回灌时 ST_GeomFromText 还原）。
"""

from __future__ import annotations

import csv
import io
import json
import uuid

import psycopg

NEW_DSN = "postgresql://chinatrip:chinatrip@localhost:5432/chinatrip"
BACKUP_CSV = r"D:\CHINATRIP\CHINATRIP CODES\ops\pois_inactive_purge_backup_2026-11-03.csv"
MUSEUM_CSV = r"D:\CHINATRIP\tmp_unesco\museum_restore.csv"
MUSEUM_SOURCES = ("museum1", "museum2", "museum3", "artmuseum")

NEW_UNESCO_ROWS = [
    {
        "source": "unesco",
        "source_poi_id": "unesco_whc_779",
        "city": "乐山",
        "name_zh": "峨眉山—乐山大佛",
        "name_en": "Mount Emei Scenic Area, including Leshan Giant Buddha Scenic Area",
        "category": "attraction",
        "status": "active",
        "origin": "unesco",
        "tags": ["unesco"],
        "tags_source": "labels",
    },
    {
        "source": "unesco",
        "source_poi_id": "unesco_whc_1559",
        "city": "铜仁",
        "name_zh": "梵净山",
        "name_en": "Fanjingshan",
        "category": "nature",
        "status": "active",
        "origin": "unesco",
        "tags": ["unesco"],
        "tags_source": "labels",
    },
]


def jsonb_cols(cur) -> set[str]:
    cur.execute(
        "select column_name from information_schema.columns "
        "where table_name='pois' and data_type='jsonb'"
    )
    return {r[0] for r in cur.fetchall()}


def _jsonify(v):
    """jsonb 列参数归一：Python 对象→JSON 串；单引号 repr 串→还原为合法 JSON。"""
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, str):
        try:
            json.loads(v)
            return v
        except (ValueError, TypeError):
            import ast

            return json.dumps(ast.literal_eval(v), ensure_ascii=False)
    return v


def insert_row(cur, row: dict, jcols: set[str], geom_cols=("location", "wgs84_location")) -> None:
    cols = list(row)
    if "id" not in cols:  # 活库 pois.id 无服务端默认（app 层 uuid4 生成），此处同法补齐
        row = {"id": str(uuid.uuid4()), **row}
        cols = list(row)
    vals = []
    for c in cols:
        v = row[c]
        if c in geom_cols:
            vals.append(psycopg.sql.SQL("ST_GeomFromText(NULLIF(%s,'')::text)"))
        elif c in jcols:
            vals.append(psycopg.sql.SQL("NULLIF(%s,'')::jsonb"))
        else:
            vals.append(psycopg.sql.SQL("%s"))
    col_sql = psycopg.sql.SQL(", ".join(f'"{c}"' for c in cols))
    ph = psycopg.sql.SQL(",").join(vals)
    q = psycopg.sql.SQL(
        "insert into pois ({cols}) values ({ph}) "
        "on conflict (source, source_poi_id) do nothing"
    ).format(cols=col_sql, ph=ph)
    params = []
    for c in cols:
        v = row[c]
        if v == "" or v is None:
            params.append("" if c == "city" else None)  # 新库 city NOT NULL（泛名行存空串）
        elif c in jcols:
            params.append(_jsonify(v))
        else:
            params.append(v)
    cur.execute(q, params)


def restore_purged(cur, jcols: set[str]) -> list[str]:
    with io.open(BACKUP_CSV, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        if r["source"] != "unesco" or r["name_zh"] not in ("大足石刻", "秦始皇陵"):
            continue
        row = dict(r)
        row["status"] = "active"  # 误删回灌：§4 正典词表不命中（大足石刻在保留类样本）
        insert_row(cur, row, jcols)
        out.append(row["name_zh"])
    return out


def migrate_tianshan(old_cur, cur, jcols: set[str]) -> str:
    old_cur.execute(
        "select column_name from information_schema.columns "
        "where table_name='pois' order by ordinal_position"
    )
    cols = [r[0] for r in old_cur.fetchall() if r[0] != "id"]
    geom = {"location", "wgs84_location"}
    sel = ", ".join(
        f"ST_AsText({c}) AS {c}" if c in geom else c for c in cols
    )
    old_cur.execute(
        f"select {sel} from pois where source_poi_id='unesco_whc_1414' and source='unesco'"
    )
    rec = old_cur.fetchone()
    if rec is None:
        raise RuntimeError("新疆天山 row not found in old DB")
    row = dict(zip(cols, rec))
    insert_row(cur, row, jcols)
    return row["name_zh"]


def migrate_museums(cur, jcols: set[str]) -> dict:
    stats = {"total": 0, "inserted": 0, "conflict": 0}
    with io.open(MUSEUM_CSV, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            stats["total"] += 1
            before = cur.rowcount
            insert_row(cur, r, jcols)
            stats["inserted"] += 1 if cur.rowcount else 0
            stats["conflict"] += 0 if cur.rowcount else 1
    return stats


def main() -> int:
    with psycopg.connect(NEW_DSN, connect_timeout=5) as conn:
        cur = conn.cursor()
        jcols = jsonb_cols(cur)

        restored = restore_purged(cur, jcols)
        print("restored_from_backup:", restored)

        with psycopg.connect(
            "postgresql://chinatrip:chinatrip@127.0.0.1:5433/chinatrip",
            connect_timeout=5,
        ) as old_conn:
            old_cur = old_conn.cursor()
            print("migrated:", migrate_tianshan(old_cur, cur, jcols))

        for r in NEW_UNESCO_ROWS:
            row = dict(r)
            row["tags"] = json.dumps(row["tags"], ensure_ascii=False)
            insert_row(cur, row, jcols)
            print("created:", row["name_zh"])

        cur.execute("commit")

    with io.open(MUSEUM_CSV, encoding="utf-8-sig", newline="") as f:
        n = sum(1 for _ in f) - 1
    print("museum_restore.csv rows:", n)

    with psycopg.connect(NEW_DSN, connect_timeout=5) as conn:
        cur = conn.cursor()
        stats = migrate_museums(cur, jcols)
        print("museum_migrate:", stats)
        cur.execute("commit")
        cur.execute(
            "select source, count(*) from pois where source in "
            "('museum1','museum2','museum3','artmuseum','unesco') group by source order by source"
        )
        for r in cur.fetchall():
            print("verify:", r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
