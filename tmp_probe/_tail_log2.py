import io, re
raw = io.open(r"D:\chinatrip\uvicorn_h5_1018e.log", encoding="utf-8", errors="replace", newline="").read()
idx = [m.start() for m in re.finditer(r"Traceback", raw)]
seg = raw[idx[-1]:idx[-1]+5200]
# keep only lines mentioning our app files or the final error
keep = []
for line in seg.splitlines():
    if ("CHINATRIP" in line or "Error" in line or "raise" in line or line.strip().startswith("^")):
        keep.append(line.rstrip())
print("\n".join(keep[-25:]))
