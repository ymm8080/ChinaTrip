import sqlite3, json
conn = sqlite3.connect(r"D:\chinatrip\CHINATRIP CODES\data\h5_state.db")
conn.row_factory = sqlite3.Row
rows = conn.execute("select session_id, payload from plan_sessions order by rowid desc limit 8").fetchall()
for r in rows:
    d = json.loads(r["payload"])
    print("==== ", r["session_id"], " keys:", sorted(d.keys()))
