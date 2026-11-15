# Backfill trip_items payload jsonb with column values for the 8 restored
# scheduled rows. PgTripItemService._pg_reload_items treats payload as read
# authority, so payload must carry the same position the column holds.
import psycopg2

SQL = """
UPDATE trip_items
SET payload = payload || jsonb_build_object(
    'name', name,
    'city', city,
    'note', note,
    'status', status,
    'source', source,
    'day', day,
    'position', position::float8,
    'address', address,
    'opening_hours', opening_hours
)
WHERE status = 'scheduled'
RETURNING payload->>'name', payload->>'position';
"""

conn = psycopg2.connect(
    host="localhost", dbname="chinatrip", user="chinatrip", password="chinatrip"
)
cur = conn.cursor()
cur.execute(SQL)
rows = cur.fetchall()
conn.commit()
cur.close()
conn.close()
print(f"updated {len(rows)} rows")
for name, pos in rows:
    print(f"  {pos}  {name}")
