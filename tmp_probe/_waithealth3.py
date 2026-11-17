import time, urllib.request
ok = False
for i in range(90):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8443/health", timeout=6) as r:
            print(8443, r.status, r.read().decode()[:80]); ok = True; break
    except Exception:
        time.sleep(4)
print("up" if ok else "still down")
