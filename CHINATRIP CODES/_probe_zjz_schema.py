import psycopg
from psycopg.rows import dict_row
url = "postgresql://chinatrip:chinatrip@localhost:5432/chinatrip"
with psycopg.connect(url, client_encoding="utf-8") as conn:
    cur = conn.cursor(row_factory=dict_row)
    cur.execute("""
        select column_name from information_schema.columns
        where table_name='pois' order by ordinal_position
    """)
    print("COLS:", [r["column_name"] for r in cur.fetchall()])
