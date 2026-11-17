import psycopg, json
con = psycopg.connect("postgresql://chinatrip:chinatrip@localhost:5432/chinatrip")
cur = con.cursor()
cur.execute("""
 select i.id, i.updated_at, i.title, i.travel_start_date, i.cities, i.is_deleted
 from itineraries i order by i.updated_at desc limit 12
""")
for r in cur.fetchall():
    print(r[1], str(r[0])[:8], "del=%s" % r[5], "start=%s" % r[3], (r[2] or "")[:26], r[4])
