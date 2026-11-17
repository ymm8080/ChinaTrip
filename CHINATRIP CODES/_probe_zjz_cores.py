import sys
sys.path.insert(0, r"D:\chinatrip\CHINATRIP CODES")
import psycopg
from psycopg.rows import dict_row
from app.services.poi_names import place_core_en
import re
url = "postgresql://chinatrip:chinatrip@localhost:5432/chinatrip"
cores = {}
with psycopg.connect(url, client_encoding="utf-8") as conn:
    cur = conn.cursor(row_factory=dict_row)
    cur.execute("select city, name_zh, name_en, category from pois where (status is null or status='active')")
    for r in cur.fetchall():
        if r["category"] and "hotel" in (r["category"] or "").lower():
            continue
        en = r["name_en"] or ""
        if re.search(r"[\u4e00-\u9fff]", en):
            continue
        core = place_core_en(en)
        toks = core.split()
        if len(toks) == 1 and len(toks[0]) >= 6:
            cores.setdefault(toks[0].lower(), []).append((r["city"], r["name_zh"], en))
print("single-token cores:", len(cores))
# collision audit: any two cores with common prefix >= 6?
items = sorted(cores)
def cp(a, b):
    n = 0
    for x, y in zip(a, b):
        if x != y: break
        n += 1
    return n
def ld(a, b):
    if len(a) < len(b): a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        currow = [i]
        for j, cb in enumerate(b, 1):
            currow.append(min(prev[j] + 1, currow[j-1] + 1, prev[j-1] + (ca != cb)))
        prev = currow
    return prev[-1]
bad = []
for i in range(len(items)):
    for j in range(i + 1, len(items)):
        a, b = items[i], items[j]
        if cp(a, b) >= 5 and ld(a, b) <= 4:
            bad.append((a, b, cp(a, b), ld(a, b)))
print("collisions cp>=5 ld<=4:", len(bad))
for t in bad[:30]: print("  ", t)
bad6 = [t for t in bad if t[2] >= 6]
print("collisions cp>=6 ld<=4:", len(bad6))
for t in bad6[:30]: print("  ", t)
