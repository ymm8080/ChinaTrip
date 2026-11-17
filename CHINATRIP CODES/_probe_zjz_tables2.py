import psycopg
from psycopg.rows import dict_row
url = "postgresql://chinatrip:chinatrip@localhost:5432/chinatrip"
with psycopg.connect(url, client_encoding="utf-8") as conn:
    cur = conn.cursor(row_factory=dict_row)
    cur.execute("""
        select table_name from information_schema.tables
        where table_schema='public' order by table_name
    """)
    print([r["table_name"] for r in cur.fetchall()])
