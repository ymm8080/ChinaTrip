import psycopg
con = psycopg.connect("postgresql://chinatrip:chinatrip@localhost:5432/chinatrip")
cur = con.cursor()
cur.execute("select date, rise_time, lower_time from flag_schedule order by date")
rows = cur.fetchall()
print("n=", len(rows), "range", rows[0], rows[-1])
for d, r, l in rows:
    if str(d) >= "2026-11-14" and str(d) <= "2026-11-28":
        print(d, r, l)
