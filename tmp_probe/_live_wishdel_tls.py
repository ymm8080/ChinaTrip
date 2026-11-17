import time, urllib.request, ssl, json
ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
BASE = "https://127.0.0.1:8443"
DEV = "probe-wishdel-1114"
def call(method, path, body=None, timeout=150):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json"); req.add_header("X-Device-ID", DEV)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            raw = r.read().decode("utf-8"); return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try: return e.code, json.loads(raw)
        except Exception: return e.code, raw

t0=time.time()
st, body = call("POST", "/api/v1/plan/start", {"cities": ["上海"], "days": 1, "preferences": "地标"})
print("start", st, "%.1fs"%(time.time()-t0), body.get("state"))
sid, iid = body.get("session_id"), (body.get("plan") or {}).get("itinerary_id")
print("sid", sid, "iid", iid)
st, body = call("POST", f"/api/v1/plan/{sid}/message", {"text": "我要去豫园"})
print("message", st, str(body.get("reply"))[:80])
st, items = call("GET", "/api/v1/trip-items")
print("BEFORE save:", st, {k:[r["name"] for r in v] for k,v in items.items() if v})
st, saved = call("POST", f"/api/v1/plan/{sid}/save", {"name": "心愿随行验证"})
print("save", st, str(saved)[:80])
st, items = call("GET", "/api/v1/trip-items")
print("AFTER save:", st, {k:[r["name"] for r in v] for k,v in items.items() if v})
st, _ = call("DELETE", f"/api/v1/itineraries/{iid}")
print("delete", st)
st, items = call("GET", "/api/v1/trip-items")
print("AFTER delete:", st, {k:[r["name"] for r in v] for k,v in items.items() if v})
