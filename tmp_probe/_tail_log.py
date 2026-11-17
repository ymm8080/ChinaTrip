import io, re
raw = io.open(r"D:\chinatrip\uvicorn_h5_1018e.log", encoding="utf-8", errors="replace", newline="").read()
idx = [m.start() for m in re.finditer(r"Traceback", raw)]
print("tracebacks:", len(idx))
if idx:
    seg = raw[idx[-1]:idx[-1]+2600]
    print(seg)
