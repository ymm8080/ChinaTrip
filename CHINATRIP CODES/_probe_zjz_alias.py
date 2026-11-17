import sys
sys.path.insert(0, r"D:\chinatrip\CHINATRIP CODES")
import psycopg
from psycopg.rows import dict_row
url = "postgresql://chinatrip:chinatrip@localhost:5432/chinatrip"
with psycopg.connect(url, client_encoding="utf-8") as conn:
    cur = conn.cursor(row_factory=dict_row)
    cur.execute("select id, city, name_zh, name_en, name_aliases, updated_at from pois where name_zh like '%陆家嘴%' and (status is null or status='active')")
    for r in cur.fetchall():
        print(r["city"], "|", r["name_zh"], "|", r["name_en"], "| aliases:", r["name_aliases"], "| updated:", r["updated_at"])
