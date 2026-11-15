import json, ssl, time, urllib.request
ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
req = urllib.request.Request("https://127.0.0.1:8443/api/v1/plan/start",
    data=json.dumps({"cities":["上海","杭州"],"days":2,"preferences":"地标"}).encode(),
    headers={"Content-Type":"application/json","X-Device-ID":"probe-smoke-wd2"}, method="POST")
t0=time.time()
try:
    with urllib.request.urlopen(req, timeout=150, context=ctx) as r:
        b=json.loads(r.read().decode()); print(r.status, "%.1fs"%(time.time()-t0), b.get("state"))
except urllib.error.HTTPError as e:
    print("HTTP", e.code, e.read().decode()[:300])
except Exception as e:
    print("ERR", type(e).__name__, e)
