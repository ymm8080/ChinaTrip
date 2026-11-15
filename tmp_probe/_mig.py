import re, io
for f in ["w12_0034_restaurant_ta_cols.py","w12_0035_trip_item_drafts.py","w12_0036_user_id_keying.py","w12_0037_poi_access_cols.py","w12_0038_poi_access_leg_cols.py"]:
    p = r"D:\CHINATRIP\CHINATRIP CODES\alembic\versions" + "\\" + f
    s = io.open(p, encoding="utf-8").read()
    rev = re.search(r"revision(?::\s*str)?\s*=\s*[\"']([^\"']+)[\"']", s)
    down = re.search(r"down_revision(?::\s*str \| None)?\s*=\s*[\"']([^\"']+)[\"']", s)
    print(f, "rev=", rev.group(1) if rev else "?", "down=", down.group(1) if down else "?")
