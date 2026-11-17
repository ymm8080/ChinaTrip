import sqlite3, json, glob
for db in [r"D:\chinatrip\h5_state.db", r"D:\chinatrip\CHINATRIP CODES\data\h5_state.db"]:
    try:
        conn = sqlite3.connect(db)
        tables = [r[0] for r in conn.execute("select name from sqlite_master where type='table'")]
        print(db, "->", tables)
        conn.close()
    except Exception as e:
        print(db, "ERR", e)
