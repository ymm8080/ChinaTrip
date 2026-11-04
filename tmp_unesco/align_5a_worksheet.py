# -*- coding: utf-8 -*-
"""5A 名单对齐底稿（§3.2 #3，离线不落库）。

包 02_CSV（baike 358 全称式）vs 库 source='5a'（规范化短名式）。两边命名体系不同，
直接 diff 仅 ~22 行命中；本脚本用 core（剥头行政区 + 剥尾类型词，循环至稳定）对齐，
产出三档判定底稿供裁决：
  exact_core   core 完全相等（确配）
  contain_core core 互为子串（省/市/区前缀或类型词差异，需人工确认）
  none         真缺口候选（新批/老漏/语义变体）
  db_only      库有包无（旧版已除名/名称体系差异/truncated 脏名，需人工判定）
输出 DESIGN/POIS DATASOURCE/_src/5a_align_worksheet.csv。
"""

from __future__ import annotations

import csv
import io
import re

import psycopg

PACK = r"DESIGN/POIS DATASOURCE/02_5A级旅游景区_358.csv"
OUT = r"DESIGN/POIS DATASOURCE/_src/5a_align_worksheet.csv"

ADMIN_HEAD = re.compile(r"^[\u4e00-\u9fa5]{1,8}?(自治区|特别行政区|自治州|地区|盟|市|县|旗|区|镇)")
TYPE_SUFFIX = re.compile(r"(旅游景区|旅游度假区|风景名胜旅游区|风景名胜区|风景旅游区|旅游风景区|旅游区|风景区|度假区|景区)$")
MIN_REMAINDER = 2
#: 剥完剩裸类型词说明剥过头，回退
TYPE_WORDS = {"景区", "旅游区", "风景区", "度假区", "风景名胜区", "旅游景区", "风景名胜旅游区", "旅游度假区"}
PUNCT_DELETE = "·－—–―・／/－-"  # 各类连接符/斜体点直接删除（两边体系不同：包有横线库常无）


def norm(name: str, keepparen: bool = False) -> str:
    """规范化：默认剥括号（曾用名）；keepparen=True 保留括号内容（括号内即站点名的情形）。"""
    n = re.sub(r"[（()）]", "", name) if keepparen else re.sub(r"[（(].*?[)）]", "", name)
    n = re.sub(r"\s+", "", n)
    for c in PUNCT_DELETE:
        n = n.replace(c, "")
    return n


def core(name: str, keepparen: bool = False) -> str:
    """剥头行政区 + 剥尾类型词，循环至稳定（只用于比对，不改数据）。"""
    n = norm(name, keepparen)
    changed = True
    while changed:
        changed = False
        n2 = TYPE_SUFFIX.sub("", n, count=1)
        if n2 != n and len(n2) >= MIN_REMAINDER:
            n, changed = n2, True
        n2 = ADMIN_HEAD.sub("", n, count=1)
        if n2 != n and len(n2) >= MIN_REMAINDER and n2 not in TYPE_WORDS:
            n, changed = n2, True
    return n


def main() -> int:
    pack = list(csv.DictReader(io.open(PACK, encoding="utf-8-sig", newline="")))
    conn = psycopg.connect(
        "postgresql://chinatrip:chinatrip@localhost:5432/chinatrip", connect_timeout=5
    )
    cur = conn.cursor()
    cur.execute("select source_poi_id, name_zh, city, status from pois where source='5a'")
    db = cur.fetchall()
    conn.close()

    db_core: dict[str, list[tuple]] = {}
    for r in db:
        db_core.setdefault(core(r[1]), []).append(r)

    out = []
    matched_db_ids = set()
    for p in pack:
        name = p["name_zh"]
        keys = []
        for kp in (False, True):
            k = core(name, kp)
            if k and k not in keys:
                keys.append(k)
        hit, mtype = None, "none"
        for key in keys:
            if key in db_core:
                hit, mtype = db_core[key][0], "exact_core"
                break
        if hit is None:
            for key in keys:
                for ck, rows in db_core.items():
                    if len(ck) >= 2 and len(key) >= 2 and (key in ck or ck in key):
                        hit, mtype = rows[0], "contain_core"
                        break
                if hit:
                    break
        if hit:
            matched_db_ids.add(hit[0])
        out.append({
            "side": "pack", "pack_name": name, "province": p["province"],
            "rated_year": p["rated_year"], "db_source_poi_id": hit[0] if hit else "",
            "db_name": hit[1] if hit else "", "db_city": hit[2] if hit else "",
            "db_status": hit[3] if hit else "", "match_type": mtype,
        })
    for r in db:
        if r[0] not in matched_db_ids:
            out.append({
                "side": "db_only", "pack_name": "", "province": "",
                "rated_year": "", "db_source_poi_id": r[0], "db_name": r[1],
                "db_city": r[2], "db_status": r[3], "match_type": "",
            })

    with io.open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)

    from collections import Counter
    pack_rows = [o for o in out if o["side"] == "pack"]
    print("worksheet:", OUT, len(out), "rows")
    print("pack match:", Counter(o["match_type"] for o in pack_rows))
    print("db_only:", sum(1 for o in out if o["side"] == "db_only"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
