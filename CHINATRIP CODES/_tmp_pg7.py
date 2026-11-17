import psycopg, json
con = psycopg.connect("postgresql://chinatrip:chinatrip@localhost:5432/chinatrip")
cur = con.cursor()
cur.execute("select id, plan, travel_start_date, cities from itineraries where id = %s", ("7785763e-4d44-5ccf-84e0-69ea8618cbb1",))
r = cur.fetchone()
p = r[1]
print("start", r[2], "cities", r[3])
for d in p.get("days") or []:
    print("== day", d.get("day"))
    for it in d.get("items") or []:
        print("   %-22s %-8s %-8s pinned=%-5s fx=%-14s kind=%s" % (str(it.get("name"))[:22], it.get("start_time"), it.get("end_time"), it.get("pinned"), it.get("fixed_sessions"), it.get("kind")))
print("assumptions:", [a for a in p.get("assumptions") or [] if "旗" in a])
