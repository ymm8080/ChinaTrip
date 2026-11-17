import psycopg, json
con = psycopg.connect("postgresql://chinatrip:chinatrip@localhost:5432/chinatrip")
cur = con.cursor()
cur.execute("""
 select id, created_at, updated_at, last_changed_at, title, travel_start_date, cities, owner_account_id, plan
 from itineraries where is_deleted = false order by coalesce(updated_at, created_at) desc limit 4
""")
for r in cur.fetchall():
    iid, ca, ua, lca, title, sd, cities, acct, plan = r
    print("=" * 80)
    print(str(iid)[:8], "created", ca, "updated", ua, "changed", lca, "title", title, "start", sd, cities, "acct", acct)
    p = plan or {}
    print("  plan.start_date", p.get("start_date"), "days", len(p.get("days") or []))
    for d in p.get("days") or []:
        print("  day", d.get("day"), "date", d.get("date"))
        for it in d.get("items") or []:
            nm = str(it.get("name"))[:16]
            print("     %-18s %-8s %-8s pinned=%s fx=%s dur=%s" % (nm, it.get("start_time"), it.get("end_time"), it.get("pinned"), it.get("fixed_sessions"), it.get("duration_minutes")))
