import sys
sys.path.insert(0, r"D:\chinatrip\CHINATRIP CODES")
import psycopg
from psycopg.rows import dict_row
url = "postgresql://chinatrip:chinatrip@localhost:5432/chinatrip"
BRIEF = ("SHANGHAI 2DAY'S TRIP INCLUDING THE BUND, SHANGHAI MUSEUM, "
         "ORITAL TOWER, CURISE, YUGARDEN ZHUJIAZUI")
with psycopg.connect(url, client_encoding="utf-8") as conn:
    cur = conn.cursor(row_factory=dict_row)
    cur.execute("""
        select id, city, name_zh, name_en, name_aliases, category, status, updated_at
        from pois
        where lower(coalesce(name_en,'')) ~ '(lujiazui|zhujia)' and (status is null or status='active')
        order by name_zh
    """)
    for r in cur.fetchall():
        print(r["city"], "|", r["name_zh"], "|", r["name_en"], "|", r["name_aliases"], "|", r["updated_at"])
