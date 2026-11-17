# -*- coding: utf-8 -*-
import io, json, time, urllib.request

BASE = "http://127.0.0.1:8000"
DEV = "probe-wishdel-1114"

def call(method, path, body=None, timeout=90):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Device-ID", DEV)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8")
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw

# 1) start a fresh plan (draft, NOT saved)
t0 = time.time()
st, body = call("POST", "/api/v1/plan/start", {
    "cities": ["上海"], "days": 1, "preferences": "地标",
})
print("start", st, "%.1fs" % (time.time() - t0), body.get("state"))
sid = body["session_id"]
iid = body["plan"]["itinerary_id"]
print("sid", sid, "iid", iid)

# 2) chat a wish (fast lane)
st, body = call("POST", f"/api/v1/plan/{sid}/message", {"text": "我要去豫园"}, timeout=120)
print("message", st, (body.get("reply") or "")[:60])

# 3) trip-items before save -> wishlist must be empty (draft hidden)
st, items = call("GET", "/api/v1/trip-items")
names = [r["name"] for g in items.values() for r in g]
print("BEFORE save trip-items:", st, names, "| wish zone:", [r["name"] for r in items.get("wishlist", [])])

# 4) save
st, saved = call("POST", f"/api/v1/plan/{sid}/save", {"name": "心愿随行验证"}, timeout=120)
print("save", st, saved.get("name"), saved.get("sync_version"))

st, items = call("GET", "/api/v1/trip-items")
print("AFTER save trip-items wish zone:", [r["name"] for r in items.get("wishlist", [])],
      "scheduled:", [r["name"] for r in items.get("scheduled", [])])

# 5) delete itinerary -> related wishlist must be gone
st, _ = call("DELETE", f"/api/v1/itineraries/{iid}")
print("delete", st)
st, items = call("GET", "/api/v1/trip-items")
print("AFTER delete trip-items all:", {k: [r["name"] for r in v] for k, v in items.items() if v})
