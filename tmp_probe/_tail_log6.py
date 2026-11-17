import io, re
raw = io.open(r"D:\chinatrip\uvicorn_h5_1018e.log", encoding="utf-8", errors="replace", newline="").read()
idx = [m.start() for m in re.finditer(r"Traceback", raw)]
seg = raw[idx[-1]:]
# find last "Error: ..." line and the app frames
err = [m for m in re.finditer(r"^.*(AttributeError|TypeError|KeyError|ValueError|NameError|ImportError).*$", seg, re.M)]
for m in err[-3:]:
    print(m.group(0).strip()[:200])
frames = [m.group(0).strip() for m in re.finditer(r'File "D:\\CHINATRIP[^"]+", line \d+, in \w+', seg)]
print("APP FRAMES:")
for f in frames[-8:]:
    print("  ", f)
