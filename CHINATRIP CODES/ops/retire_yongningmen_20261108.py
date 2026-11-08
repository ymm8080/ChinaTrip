# -*- coding: utf-8 -*-
"""西安永宁门退役（2026-11-08 用户拍板「永宁门就不应该被选中」）。

永宁门=西安城墙南门，城墙本体已由 5A 组合行「城墙·碑林历史文化景区」
（5a_304）覆盖；独立行（baidu 源）入选即同实体重复占座（活服 11-08
西安 5 天案实录：day1 独立永宁门卡 + day3 城墙·碑林组合卡，同一堵墙
排了两天）。

处置=软删让位（status='inactive'，11-07 错针批量退役同口径）：
- 退役前查同城 active 同实体（组合行须在池）；
- 快照表 pois_dupgate_bak_20261108 + 全字段 CSV；
- UPDATE 带 status='active' 守卫，行数不符即记异常。
- 附带扫描其余城门行（安远门/安定门/长乐门等）只报告不动库。

用法：python ops/retire_yongningmen_20261108.py [--apply]
回滚：UPDATE pois SET status='active', updated_at=NOW()
      WHERE name_zh='永宁门' AND city='西安';
"""

import csv
import io
import json
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, text

sys.stdout.reconfigure(encoding="utf-8")

APPLY = "--apply" in sys.argv

HERE = Path(__file__).resolve().parent
DSN = "postgresql+psycopg://chinatrip:chinatrip@localhost:5432/chinatrip"
BAK_TABLE = "pois_dupgate_bak_20261108"
OUT_CSV = HERE / "pois_retired_backup_2026-11-08_yongningmen.csv"

GATE_NAMES = (
    "安远门",
    "安定门",
    "长乐门",
    "尚德门",
    "尚俭门",
    "尚武门",
    "建国门",
    "和平门",
    "文昌门",
    "勿幕门",
    "玉祥门",
    "中山门",
)

eng = create_engine(DSN, connect_args={"connect_timeout": 3})

with eng.connect() as c:
    target = c.execute(
        text(
            "select id, name_zh, source_poi_id, category, status, address, "
            "rating, ST_X(location::geometry) as lon, "
            "ST_Y(location::geometry) as lat "
            "from pois where city='西安' and name_zh='永宁门'"
        )
    ).mappings().all()
    keeper = c.execute(
        text(
            "select id, name_zh, source_poi_id, status, rating "
            "from pois where city='西安' "
            "and name_zh like '%城墙%' and status='active'"
        )
    ).mappings().all()
    other_gates = c.execute(
        text(
            "select id, name_zh, source_poi_id, category, status "
            "from pois where city='西安' and name_zh = any(:names)"
        ),
        {"names": list(GATE_NAMES)},
    ).mappings().all()

print("== 目标行（永宁门/西安）==")
for r in target:
    print(dict(r))
print("== 城墙接位行（active）==")
for r in keeper:
    print(dict(r))
print("== 其余城门行（只报告不动库）==")
for r in other_gates:
    print(dict(r))

active_targets = [r for r in target if r["status"] == "active"]
if len(active_targets) != 1:
    print(f"!! 永宁门 active 行数={len(active_targets)}（预期 1），中止")
    sys.exit(1)
if not keeper:
    print("!! 城墙接位行（5a_304 组合）不在池，中止——退役会丢城墙本体")
    sys.exit(1)

ids = [str(active_targets[0]["id"])]

if APPLY:
    with eng.begin() as c:
        c.execute(
            text(
                f"create table if not exists {BAK_TABLE} as "
                "select * from pois where false"
            )
        )
        c.execute(
            text(
                f"insert into {BAK_TABLE} select * from pois where id in :ids "
                "and id not in (select id from " + BAK_TABLE + ")"
            ).bindparams(__import__("sqlalchemy").bindparam("ids", expanding=True)),
            {"ids": ids},
        )
    with eng.connect() as c:
        snap = c.execute(
            text("select * from pois where id in :ids").bindparams(
                __import__("sqlalchemy").bindparam("ids", expanding=True)
            ),
            {"ids": ids},
        ).mappings().all()
    cols = list(snap[0].keys())

    def cell(v):
        if v is None:
            return ""
        if isinstance(v, (dict, list)):
            return json.dumps(v, ensure_ascii=False)
        return str(v)

    with io.open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in snap:
            w.writerow([cell(r[k]) for k in cols])
    with eng.begin() as c:
        for pid in ids:
            res = c.execute(
                text(
                    "update pois set status='inactive', updated_at=NOW() "
                    "where id=:id and status='active'"
                ),
                {"id": pid},
            )
            if res.rowcount != 1:
                print(f"!! rowcount={res.rowcount} for {pid}")
                sys.exit(1)
    with eng.connect() as c:
        after = c.execute(
            text(
                "select id, name_zh, status from pois "
                "where city='西安' and name_zh='永宁门'"
            )
        ).mappings().all()
    print("== 退役后 ==")
    for r in after:
        print(dict(r))
    print(
        f"APPLY 完成 {datetime.now().isoformat(timespec='seconds')}；"
        f"快照表 {BAK_TABLE}，CSV {OUT_CSV.name}"
    )
else:
    print(f"DRY-RUN（--apply 执行）：将退役 {ids}，接位行 {keeper[0]['name_zh']}")
