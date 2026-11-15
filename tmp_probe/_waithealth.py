import time, urllib.request, sys
for port in (8000, 8443):
    for i in range(40):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=6) as r:
                print(port, r.status, r.read().decode()[:60]); break
        except Exception as e:
            time.sleep(3)
    else:
        print(port, "NOT UP")
