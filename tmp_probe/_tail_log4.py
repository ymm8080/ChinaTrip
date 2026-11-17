import io, re
raw = io.open(r"D:\chinatrip\uvicorn_h5_1018e.log", encoding="utf-8", errors="replace", newline="").read()
idx = [m.start() for m in re.finditer(r"Traceback", raw)]
seg = raw[idx[-1]:idx[-1]+12000]
lines = seg.splitlines()
for i, l in enumerate(lines):
    if ("app" in l and ".py" in l and "site-packages" not in l) or re.search(r"\w*(Error|Exception):", l):
        print(i, l.rstrip()[:200])
