# -*- coding: utf-8 -*-
"""组件重复·三组人工拍板批退役（2026-11-08，用户拍板「leave 5a」）。

范围=组件重复全库扫（component_dup_scan_20261108.md）MANUAL-名称包含类
三组真同实体对，处置口径：**留 5A 组合行原样（不改名），退役通行名弱源行**；
败者名并入 keeper.name_aliases 保愿望/点名匹配；快照表
pois_component_bak_20261108 + 全字段 CSV；UPDATE 带 status='active' 守卫。

- 恭王府(ct_北京_5)   → 西城区恭王府景区(5a_006)
- 同里古镇(ct_苏州_8)  → 吴江区同里古镇景区(5a_072)（两行坐标逐位相同）
- 明十三陵(ct_北京_16) → 昌平区明十三陵景区(5a_005)

组件组（定陵/昭陵/神路/三潭印月/白堤/二王庙/安澜桥/玉垒阁/罗星洲/
珍珠塔/濯水古镇/托木尔）未获拍板，不在本批。

用法：python ops/retire_component_batch_20261108.py [--apply]
回滚（逐行）：UPDATE pois SET status='active', updated_at=NOW() WHERE id='<败者id>';
"""

import csv
import io
import json
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import bindparam, create_engine, text

sys.stdout.reconfigure(encoding="utf-8")

APPLY = "--apply" in sys.argv

HERE = Path(__file__).resolve().parent
DSN = "postgresql+psycopg://chinatrip:chinatrip@localhost:5432/chinatrip"
BAK_TABLE = "pois_component_bak_20261108"
OUT_CSV = HERE / "pois_retired_backup_2026-11-08_component_batch2.csv"

PAIRS = [
    ("北京", "恭王府", "西城区恭王府景区"),
    ("苏州", "同里古镇", "吴江区同里古镇景区"),
    ("北京", "明十三陵", "昌平区明十三陵景区"),
]


def cell(v):
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


eng = create_engine(DSN, connect_args={"connect_timeout": 3})
plan = []
with eng.connect() as c:
    for city, loser_nm, keeper_nm in PAIRS:
        loser = c.execute(
            text(
                "select id, name_zh, source_poi_id, status from pois "
                "where city=:c and name_zh=:n and status='active'"
            ),
            {"c": city, "n": loser_nm},
        ).mappings().all()
        keeper = c.execute(
            text(
                "select id, name_zh, source_poi_id, name_aliases, status "
                "from pois where city=:c and name_zh=:n and status='active'"
            ),
            {"c": city, "n": keeper_nm},
        ).mappings().all()
        if len(loser) != 1 or len(keeper) != 1:
            print(f"!! {city} {loser_nm}: loser={len(loser)} keeper={len(keeper)} 预期各1，跳过")
            continue
        lo, kp = loser[0], keeper[0]
        if not str(kp["source_poi_id"] or "").startswith("5a_"):
            print(f"!! {city} keeper 源非 5a_（{kp['source_poi_id']}），越拍板范围，跳过")
            continue
        refs = c.execute(
            text("select count(*) from trip_items where poi_id=:i"), {"i": lo["id"]}
        ).scalar() + c.execute(
            text("select count(*) from itinerary_items where poi_id=:i"), {"i": lo["id"]}
        ).scalar()
        plan.append({"city": city, "lo": lo, "kp": kp, "refs": refs})
        aliases = kp["name_aliases"] or []
        print(
            f"OK {city}: {lo['name_zh']}({lo['source_poi_id']}) -> "
            f"{kp['name_zh']}({kp['source_poi_id']}) refs={refs} "
            f"aliases={aliases}"
        )

if len(plan) != len(PAIRS):
    print(f"!! 守卫不过（{len(plan)}/{len(PAIRS)}），中止")
    sys.exit(1)

ids = [str(p["lo"]["id"]) for p in plan]
if not APPLY:
    print(f"DRY-RUN（--apply 执行）：将退役 {ids}")
    sys.exit(0)

with eng.begin() as c:
    c.execute(
        text(
            f"create table if not exists {BAK_TABLE} as select * from pois where false"
        )
    )
    c.execute(
        text(
            f"insert into {BAK_TABLE} select * from pois where id in :ids "
            "and id not in (select id from " + BAK_TABLE + ")"
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": ids},
    )
with eng.connect() as c:
    snap = c.execute(
        text("select * from pois where id in :ids").bindparams(
            bindparam("ids", expanding=True)
        ),
        {"ids": ids},
    ).mappings().all()
cols = list(snap[0].keys())
with io.open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f)
    w.writerow(cols)
    for r in snap:
        w.writerow([cell(r[k]) for k in cols])

with eng.begin() as c:
    for p in plan:
        lo, kp = p["lo"], p["kp"]
        aliases = list(kp["name_aliases"] or [])
        if lo["name_zh"] not in aliases:
            aliases.append(lo["name_zh"])
        res = c.execute(
            text(
                "update pois set name_aliases=:al, updated_at=NOW() "
                "where id=:id and status='active'"
            ),
            {"al": json.dumps(aliases, ensure_ascii=False), "id": kp["id"]},
        )
        if res.rowcount != 1:
            print(f"!! keeper 别名更新 rowcount={res.rowcount} {kp['name_zh']}")
            sys.exit(1)
        res = c.execute(
            text(
                "update pois set status='inactive', updated_at=NOW() "
                "where id=:id and status='active'"
            ),
            {"id": lo["id"]},
        )
        if res.rowcount != 1:
            print(f"!! 退役 rowcount={res.rowcount} {lo['name_zh']}")
            sys.exit(1)

with eng.connect() as c:
    for city, loser_nm, keeper_nm in PAIRS:
        rows = c.execute(
            text(
                "select name_zh, source_poi_id, status, name_aliases from pois "
                "where city=:c and name_zh in (:a,:b)"
            ),
            {"c": city, "a": loser_nm, "b": keeper_nm},
        ).mappings().all()
        print(f"after {city}:", [dict(r) for r in rows])
print(
    f"APPLY 完成 {datetime.now().isoformat(timespec='seconds')}；"
    f"快照表 {BAK_TABLE}，CSV {OUT_CSV.name}"
)
