import sqlite3, json
conn = sqlite3.connect(r"D:\chinatrip\CHINATRIP CODES\data\h5_state.db")
conn.row_factory = sqlite3.Row
cols = [r["name"] for r in conn.execute("pragma table_info(plan_sessions)")]
print("COLS:", cols)
rows = conn.execute("select * from plan_sessions order by rowid desc limit 40").fetchall()
for r in rows:
    payload = r["payload"] if "payload" in r.keys() else ""
    if "zhujiazui" in (payload or "").lower() or "朱家嘴" in (payload or "") or "陆家嘴" in (payload or ""):
        print("HIT rowid", r["rowid"], "id", r["id"] if "id" in r.keys() else "?", "updated", r["updated_at"] if "updated_at" in r.keys() else "?")
