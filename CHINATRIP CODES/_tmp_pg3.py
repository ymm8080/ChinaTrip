import psycopg, json
con = psycopg.connect("postgresql://chinatrip:chinatrip@localhost:5432/chinatrip")
cur = con.cursor()
cur.execute("select column_name from information_schema.columns where table_name='itineraries' order by ordinal_position")
print("itineraries cols:", [r[0] for r in cur.fetchall()])
cur.execute("""
 select i.id, i.updated_at, it.day, it.name, it.start_time, it.end_time, it.pinned,
        it.payload->>'fixed_sessions' as fx
 from itinerary_items it join itineraries i on i.id = it.itinerary_id
 where it.name like '%天安门%'
 order by i.updated_at desc limit 12
""")
for r in cur.fetchall():
    print(r)
