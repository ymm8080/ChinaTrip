import sqlite3, json, os
p = "h5_state.db"
con = sqlite3.connect(p)
tabs = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
print("tables:", tabs)
for t in tabs:
    try:
        n = con.execute("select count(*) from %s" % t).fetchone()[0]
        print("  %-28s %s" % (t, n))
    except Exception as e:
        print("  ", t, "ERR", e)
