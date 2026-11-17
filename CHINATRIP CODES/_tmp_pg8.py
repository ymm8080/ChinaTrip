import psycopg, json
con = psycopg.connect("postgresql://chinatrip:chinatrip@localhost:5432/chinatrip")
cur = con.cursor()
cur.execute("select id, plan, travel_start_date from itineraries where id in (%s, %s)", ("8f5acff3-4dc4-50de-9b8b-6751c1c4c313", "d3396c10-262d-5544-83a2-8c43c0114f60"))
for iid, p, sd in cur.fetchall():
    print("=" * 60); print(str(iid)[:8], "start", sd, "plan.start_date", (p or {}).get("start_date"))
    for d in (p or {}).get("days") or []:
        print("  day", d.get("day"), "date", d.get("date"), "label", d.get("date_label"))
        for it in d.get("items") or []:
            if "天安门" in str(it.get("name")):
                print("     ", it.get("name"), it.get("start_time"), it.get("end_time"), it.get("fixed_sessions"))
