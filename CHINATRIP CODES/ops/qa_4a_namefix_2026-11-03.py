# -*- coding: utf-8 -*-
"""4A 批名称修正（qa_4a_report 2026-11-03 遗留③，3 行，CSV+DB 同步）。

源数据脏名（qa 报告 E 节，均为 13 号 CSV 同脏、非导入引入）：
  CSV 第 80 行  「（曾用名：刺树丫口景区，2023年7月变更」→「刺树丫口景区」
                （源行自证的曾用名=库内已有别名；更名后现名源页附件不可得，
                 原文挪 remark 注待核。云南文旅厅页 418 拒抓、名录在附件）
  CSV 第1036行  「翡翠谷景区景区」→「翡翠谷景区」（与其自身 alias_zh 列对齐）
  CSV 第4074行  「北陵公园(清昭陵）」→「北陵公园（清昭陵）」（括号平衡）

约束：
  - CSV 只改 3 行 name_zh（与 remark），**不增删行**——source_poi_id='4a_<行号>'
    与库对齐靠行号，行号变动即断链；其余行字节不动（sha 比对验证）。
  - DB 只改 3 行 name_zh（按 id + 旧名守卫 WHERE），别名若与新名重复则去掉
    该重复项；改前落备份 CSV 可回灌。
  - 改名后对其他源做一次同名同城复扫，新撞名只报告不处理。
用法：
    .venv/Scripts/python ops/qa_4a_namefix_2026-11-03.py [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(BASE, "..", "DESIGN", "POIS DATASOURCE",
                        "13_4A级旅游景区_官方汇编4674.csv")
CSV_BAK = CSV_PATH + ".pre_namefix_2026-11-03.backup"
DB_BAK = os.path.join(BASE, "ops", "qa_4a_namefix_backup_2026-11-03.csv")

# (csv 行号 1-based 数据行, 旧名, 新名, remark 追加文本)
FIXES = [
    (80, "（曾用名：刺树丫口景区，2023年7月变更", "刺树丫口景区",
     "原名记录：曾用名刺树丫口景区，2023年7月变更（现名待核，源页名录附件未含条目原文）"),
    (1036, "翡翠谷景区景区", "翡翠谷景区", "源行名叠字修正（与自身 alias_zh 对齐）"),
    (4074, "北陵公园(清昭陵）", "北陵公园（清昭陵）", "括号平衡修正"),
]


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:12]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # ── CSV 侧 ────────────────────────────────────────────────────────
    with io.open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    fix_by_no = {n: (old, new, extra) for n, old, new, extra in FIXES}
    for n, (old, new, extra) in fix_by_no.items():
        assert rows[n - 1]["name_zh"] == old, f"第{n}行名称不匹配: {rows[n-1]['name_zh']!r}"
    raw_before = sha(open(CSV_PATH, "rb").read())

    if not args.dry_run:
        shutil.copy2(CSV_PATH, CSV_BAK)
        for n, (old, new, extra) in fix_by_no.items():
            r = rows[n - 1]
            r["remark"] = (r["remark"] + "；" + extra) if r["remark"] else extra
            r["name_zh"] = new
        with io.open(CSV_PATH, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        raw_after = sha(open(CSV_PATH, "rb").read())
        print(f"[csv] {raw_before} -> {raw_after}, rows={len(rows)} (备份 {CSV_BAK})")
    else:
        print(f"[csv] dry-run: 将改 {len(FIXES)} 行, rows={len(rows)}")

    # ── DB 侧 ─────────────────────────────────────────────────────────
    from sqlalchemy import create_engine, text
    from app.models import Poi

    e = create_engine("postgresql+psycopg://chinatrip:chinatrip@localhost:5432/chinatrip")
    with e.connect() as c:
        id_rows = c.execute(text("""
            SELECT id, source_poi_id, name_zh, name_aliases FROM pois
            WHERE source='4a' AND name_zh = ANY(:olds)
        """), {"olds": list(old for _, old, _, _ in FIXES)}).fetchall()

    by_old = {r[2]: r for r in id_rows}
    if len(by_old) != len(FIXES):
        missing = {old for _, old, _, _ in FIXES} - set(by_old)
        raise SystemExit(f"DB 侧缺行: {missing}")

    if not args.dry_run:
        with io.open(DB_BAK, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "source_poi_id", "name_zh_old", "name_aliases_old"])
            for r in id_rows:
                w.writerow([r[0], r[1], r[2], r[3]])

    sess = None
    if not args.dry_run:
        from sqlalchemy.orm import Session
        sess = Session(e)
    try:
        for n, old, new, _extra in FIXES:
            r = by_old[old]
            aliases = r[3] or []
            kept = [a for a in aliases if a != new]  # 与新名重复的别名去掉
            print(f"[db] 4a_{n}: {old!r} -> {new!r}, aliases {aliases} -> {kept}")
            if sess:
                poi = sess.get(Poi, r[0])
                poi.name_zh = new
                poi.name_aliases = kept
        if sess:
            sess.commit()
            print(f"[db] committed, 备份 {DB_BAK}")
    finally:
        if sess:
            sess.close()

    # ── 改名后跨源同名同城复扫（只报告） ──────────────────────────────
    with e.connect() as c:
        for _n, _old, new, _e in FIXES:
            hits = c.execute(text("""
                SELECT source, status, city FROM pois
                WHERE name_zh = :n AND source <> '4a'
            """), {"n": new}).fetchall()
            for src, st, city in hits:
                print(f"[cross] {new} | {city} | {src}({st})")


if __name__ == "__main__":
    main()
