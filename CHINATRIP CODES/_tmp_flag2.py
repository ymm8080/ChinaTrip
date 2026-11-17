import sqlite3
con = sqlite3.connect("data/flag_cache.db")
rows = con.execute("select date, rise_time, lower_time, source, fetched_at from flag_schedule where date between '2026-11-14' and '2026-11-30' order by date, fetched_at").fetchall()
last = {}
for d, r, l, s, f in rows:
    last[d] = (r, l, s, f)
for d in sorted(last):
    print(d, last[d])
