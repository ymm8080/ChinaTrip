import sqlite3, json
conn = sqlite3.connect(r"D:\chinatrip\CHINATRIP CODES\data\h5_state.db")
conn.row_factory = sqlite3.Row
rows = conn.execute("select session_id, payload from plan_sessions order by rowid desc limit 60").fetchall()
for r in rows:
    d = json.loads(r["payload"])
    ws = d.get("wish_sources") or {}
    sc = d.get("site_cities") or {}
    mv = d.get("must_visits") or []
    pw = d.get("pending_wish_cities") or []
    flat = json.dumps({"ws": ws, "sc": sc, "mv": mv, "pw": pw}, ensure_ascii=False)
    if "陆家嘴" in flat or "朱家嘴" in flat or "zhujiazui" in flat.lower():
        print("==== session", r["session_id"], "cities", d.get("cities"), "state", d.get("state"))
        print("  must_visits:", mv)
        print("  pending_wish_cities:", pw)
        print("  site_cities:", sc)
        print("  wish_sources:", json.dumps(ws, ensure_ascii=False)[:500])
        hist = d.get("history") or []
        for m in hist[-10:]:
            c = m.get("content") if isinstance(m, dict) else str(m)
            if isinstance(c, list): c = " ".join(str(x) for x in c)
            print("  ", m.get("role") if isinstance(m, dict) else "?", ":", str(c)[:260].replace("\n", " | "))
