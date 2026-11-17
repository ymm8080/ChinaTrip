import psycopg, json
con = psycopg.connect("postgresql://chinatrip:chinatrip@localhost:5432/chinatrip")
cur = con.cursor()
cur.execute("select column_name, data_type from information_schema.columns where table_name='itinerary_items' order by ordinal_position")
print(cur.fetchall())
