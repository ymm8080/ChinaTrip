import psycopg, json
con = psycopg.connect("postgresql://chinatrip:chinatrip@localhost:5432/chinatrip")
cur = con.cursor()
cur.execute("select table_name from information_schema.tables where table_schema='public' order by 1")
print([r[0] for r in cur.fetchall()])
