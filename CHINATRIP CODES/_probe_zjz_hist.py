import sqlite3, json
conn = sqlite3.connect(r"D:\chinatrip\CHINATRIP CODES\data\h5_state.db")
conn.row_factory = sqlite3.Row
rows = conn.execute("select session_id, payload from plan_sessions order by rowid desc limit 60").fetchall()
for r in rows:
    d = json.loads(r["payload"])
    hist = d.get("history") or []
    text = json.dumps(hist, ensure_ascii=False).lower()
    if "zhujiazui" in text or "朱家嘴" in json.dumps(hist, ensure_ascii=False):
        print("==== session", r["session_id"], "cities", d.get("cities"), "state", d.get("state"))
        for m in hist[-16:]:
            role = m.get("role") if isinstance(m, dict) else "?"
            c = m.get("content") if isinstance(m, dict) else str(m)
            if isinstance(c, list): c = " ".join(str(x) for x in c)
            print("  ", role, ":", str(c)[:400].replace("\n", " | "))
        break
