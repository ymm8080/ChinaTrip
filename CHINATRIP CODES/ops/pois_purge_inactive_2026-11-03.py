# -*- coding: utf-8 -*-
"""硬删 inactive 池（2026-11-03，用户指令：delete items marked inactive）。

前情：红色出池两轮软删后 status='inactive' 共 719 行（active 13756）。
本脚本：先全列备份到 ops/pois_inactive_purge_backup_2026-11-03.csv（可回灌），
再删 5 张子表中对 inactive 的引用（当前为 0 行，防御性），最后删 pois inactive。
删后校验 active 13756 / inactive 0。
"""

import csv
import io
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, text

OUT_CSV = Path(__file__).parent / "pois_inactive_purge_backup_2026-11-03.csv"

COLS_SKIP = {"location", "wgs84_location"}  # geometry 列单独按 WKT 导出


def main() -> int:
    eng = create_engine(
        "postgresql+psycopg://chinatrip:chinatrip@localhost:5432/chinatrip",
        connect_args={"connect_timeout": 5},
    )
    with eng.connect() as c:
        cols = [
            r[0]
            for r in c.execute(
                text(
                    "select column_name from information_schema.columns "
                    "where table_name='pois' and table_schema='public' "
                    "order by ordinal_position"
                )
            )
        ]
        n_before = c.execute(
            text("select count(*) from pois where status='inactive'")
        ).scalar()

        # 全列备份：geometry 用 WKT，其余原值（JSONB 由驱动序列化）
        sel, hdr = [], []
        for col in cols:
            if col in COLS_SKIP:
                sel.append(f"ST_AsText({col}) AS {col}")
            else:
                sel.append(col)
            hdr.append(col)
        rows = c.execute(
            text(f"select {', '.join(sel)} from pois where status='inactive'")
        ).fetchall()

    with io.open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(hdr)
        for r in rows:
            w.writerow([str(v) if v is not None else "" for v in r])

    with eng.begin() as c:
        for tbl in [
            "poi_hours",
            "poi_reviews",
            "poi_stats",
            "trip_items",
            "itinerary_items",
        ]:
            d = c.execute(
                text(
                    f"delete from {tbl} where poi_id in "
                    "(select id from pois where status='inactive')"
                )
            )
            print(f"child {tbl}: deleted {d.rowcount}")
        dele = c.execute(text("delete from pois where status='inactive'"))
        print(f"pois inactive deleted: {dele.rowcount}")

    with eng.connect() as c:
        after = c.execute(
            text("select status, count(*) from pois group by status")
        ).fetchall()
    print("before inactive:", n_before, "| after:", after)
    print("backup csv:", OUT_CSV)
    print("done:", datetime.now().isoformat(timespec="seconds"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
