import io, re, time
raw = io.open(r"D:\chinatrip\uvicorn_h5_1018e.log", encoding="utf-8", errors="replace", newline="").read()
idx = [m.start() for m in re.finditer(r"Traceback", raw)]
# only tracebacks logged in the last 3 minutes
now_cut = None
# find last traceback and print its tail 3000 chars, filtered
seg = raw[idx[-1]:idx[-1]+4000]
print(seg[-2200:])
