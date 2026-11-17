import io, re
raw = io.open(r"D:\chinatrip\uvicorn_h5_1018e_tls.log", encoding="utf-8", errors="replace", newline="").read()
idx = [m.start() for m in re.finditer(r"Traceback", raw)]
print("tracebacks:", len(idx))
seg = raw[idx[-1]:]
frames = [m.group(0).strip() for m in re.finditer(r'File "D:\\CHINATRIP[^"]+", line \d+, in \w+', seg)]
errs = [m.group(0).strip()[:160] for m in re.finditer(r"^\w*(Error|Exception):.*$", seg, re.M)]
print("ERR:", errs[-2:])
print("FRAMES:")
for f in frames[-8:]:
    print("  ", f)
