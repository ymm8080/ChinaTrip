import psycopg
from psycopg.rows import dict_row
url = "postgresql://chinatrip:chinatrip@localhost:5432/chinatrip"
with psycopg.connect(url, client_encoding="utf-8") as conn:
    cur = conn.cursor(row_factory=dict_row)
    cur.execute("""
        select id, source, city, name_zh, name_en, category, status, rating, tags
        from pois
        where name_zh like '%朱家嘴%' or name_zh like '%朱家%' or lower(coalesce(name_en,'')) like '%zhujia%'
        order by name_zh
    """)
    for r in cur.fetchall():
        print(r["city"], "|", r["name_zh"], "|", r["name_en"], "|", r["category"], "|", r["status"], "|", r["rating"], "|", str(r["id"])[:8])
    print("---- lujiazui ----")
    cur.execute("""
        select id, source, city, name_zh, name_en, category, status, rating
        from pois
        where name_zh like '%陆家嘴%' or lower(coalesce(name_en,'')) like '%lujiazui%'
        order by name_zh
    """)
    for r in cur.fetchall():
        print(r["city"], "|", r["name_zh"], "|", r["name_en"], "|", r["category"], "|", r["status"], "|", r["rating"], "|", str(r["id"])[:8])
