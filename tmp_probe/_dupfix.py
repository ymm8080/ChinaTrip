# -*- coding: utf-8 -*-
import json, os, sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv(r"D:\CHINATRIP\CHINATRIP CODES\.env")
eng = create_engine(os.environ["DATABASE_URL"])

KEEP = "be8abf8f-7c75-48fa-9129-f49bd59c8237"   # conversation 行（保留）
DROP = "c7b1acc6-59ae-4082-977f-a0f61a7742c8"   # plan_delete 重复行

with eng.begin() as c:
    rows = c.execute(text("select id, payload from trip_items where id in (:k, :d)"), {"k": KEEP, "d": DROP}).all()
    backup = [dict(r[1]) for r in rows]
    os.makedirs(r"D:\CHINATRIP\DESIGN\backup", exist_ok=True)
    path = r"D:\CHINATRIP\DESIGN\backup\trip_items_dup_yiheyuan_2026-11-15.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(backup, f, ensure_ascii=False, indent=1, default=str)
    print("backup ->", path, len(backup))
    # 保留行承接排除标记（用户确实从另一趟行程里删过它）
    c.execute(text("""
        update trip_items
           set exclusion_flag = true,
               payload = coalesce(payload, '{}'::jsonb) || jsonb_build_object('exclusion_flag', true)
         where id = :k
    """), {"k": KEEP})
    # 重复行软删留档
    c.execute(text("""
        update trip_items
           set deletion_flag = true,
               deletion_date = current_date,
               deletion_time = localtime::time,
               deleted_by = 'dup-merge-2026-11-15',
               payload = coalesce(payload, '{}'::jsonb) || jsonb_build_object(
                   'deletion_flag', true,
                   'deleted_by', 'dup-merge-2026-11-15')
         where id = :d
    """), {"d": DROP})
with eng.connect() as c:
    for r in c.execute(text("""
        select name, status, exclusion_flag, itinerary_ref, source, deletion_flag
          from trip_items where name like '%颐和园%' order by created_at
    """)):
        print(tuple(r))
