import time, urllib.request
for i in range(60):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8443/health", timeout=6) as r:
            print(8443, r.status, r.read().decode()[:80]); break
    except Exception as e:
        time.sleep(4)
else:
    print(8443, "NOT UP after wait")
