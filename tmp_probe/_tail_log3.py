import io, re
raw = io.open(r"D:\chinatrip\uvicorn_h5_1018e.log", encoding="utf-8", errors="replace", newline="").read()
idx = [m.start() for m in re.finditer(r"Traceback", raw)]
seg = raw[idx[-1]:idx[-1]+9000]
lines = seg.splitlines()
# find the last "Error" line with a message
for i in range(len(lines)-1, -1, -1):
    if re.search(r"(Error|Exception)\b", lines[i]) and "httpx" not in lines[i] and "INFO" not in lines[i] and "GET " not in lines[i]:
        print("LINE:", lines[i].strip())
        print("CTX:")
        print("\n".join(l.rstrip() for l in lines[max(0,i-14):i+1] if "CHINATRIP" in l or "def " in l or "File \"D:" in l))
        break
