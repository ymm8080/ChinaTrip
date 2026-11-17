import sqlite3, os
for p in ("data/flag_cache.db",):
    print("==", p, os.path.exists(p))
    if not os.path.exists(p): continue
    con = sqlite3.connect(p)
    print(con.execute("select name from sqlite_master where type='table'").fetchall())
    try:
        print(con.execute("select count(*) from flag_schedule").fetchone())
        print(con.execute("select * from flag_schedule where date in ('2026-11-15','2026-11-16') order by fetched_at desc limit 6").fetchall())
        print(con.execute("select fetched_at, source, count(*) from flag_schedule group by fetched_at, source order by fetched_at desc limit 5").fetchall())
    except Exception as e:
        print("ERR", e)
