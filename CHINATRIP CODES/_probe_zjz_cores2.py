import sys, re
sys.path.insert(0, r"D:\chinatrip\CHINATRIP CODES")
import psycopg
from psycopg.rows import dict_row
from app.services.poi_names import place_core_en
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
            cores.setdefault(toks[0].lower(), []).append((r["city"], r["name_zh"]))
print(len(cores))
import collections
# any core made of common English morphemes (not pinyin)? heuristic: contains only common syllables
suspicious = [c for c in cores if re.fullmatch(r"(temple|tower|garden|museum|street|village|castle|palace|market|bridge|square|station|island|beach|lake|mount|park|plaza|hall|house|hotel|hostel|resort|cafe|bar|club|church|school|university|theater|theatre|library|airport|harbor|port|town|city|ancient|old|new|great|wall|west|east|north|south)[a-z]*", c)]
print("suspicious english-word cores:", suspicious[:20])
for c in sorted(cores):
    pass
print(sorted(cores)[:40])
