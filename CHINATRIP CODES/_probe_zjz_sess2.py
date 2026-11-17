import sqlite3, json
conn = sqlite3.connect(r"D:\chinatrip\CHINATRIP CODES\data\h5_state.db")
conn.row_factory = sqlite3.Row
rows = conn.execute("select session_id, payload from plan_sessions order by rowid desc limit 60").fetchall()
hits = []
for r in rows:
    p = (r["payload"] or "")
    low = p.lower()
    if "zhujiazui" in low or "朱家嘴" in p or "陆家嘴" in p:
        hits.append(r)
for r in hits:
    d = json.loads(r["payload"])
    print("==== session", r["session_id"])
    msgs = d.get("messages") or []
    for m in msgs[-14:]:
        role = m.get("role"); content = (m.get("content") or "")
        if isinstance(content, list):
            content = " ".join(str(c) for c in content)
        print(" ", role, ":", content[:300].replace("\n", " | "))
