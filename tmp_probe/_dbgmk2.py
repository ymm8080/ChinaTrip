import io
p = r"D:\CHINATRIP\CHINATRIP CODES\tests\test_dbg_wish.py"
t = io.open(p, encoding="utf-8").read()
t = t.replace('    print("WISH_SOURCES", session.wish_sources)', '    print("WISH_SOURCES", session.wish_sources)\n    print("SITE_CITIES", session.site_cities)\n    print("CITIES", session.cities)')
io.open(p, "w", encoding="utf-8", newline="\n").write(t)
print("ok")
