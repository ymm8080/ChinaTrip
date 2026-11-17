import sqlite3, json
conn = sqlite3.connect(r"D:\chinatrip\CHINATRIP CODES\data\h5_state.db")
row = conn.execute("select payload from plan_sessions order by rowid desc limit 1").fetchone()
d = json.loads(row[0])
print(d.get("device_id"))
