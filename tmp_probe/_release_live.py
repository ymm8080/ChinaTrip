# -*- coding: utf-8 -*-
import json, ssl, time, urllib.request
ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
BASE = "https://127.0.0.1:8443"
DEV = "probe-release-1114"
def call(method, path, body=None, headers=None, timeout=150):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items(): req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            raw = r.read().decode("utf-8"); return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try: return e.code, json.loads(raw)
        except Exception: return e.code, raw

name = "probe_release_%s" % int(time.time())
st, reg = call("POST", "/api/v1/auth/register", {"username": name, "password": "probe-pass-123", "device_id": DEV})
auth = {"Authorization": "Bearer " + reg["token"], "X-Device-ID": DEV}
print("register", st)
st, body = call("POST", "/api/v1/plan/start", {"cities": ["上海"], "days": 1, "preferences": "地标"}, headers=auth)
sid, iid = body["session_id"], body["plan"]["itinerary_id"]
print("start", st, iid)
st, body = call("POST", "/api/v1/plan/%s/message" % sid, {"text": "我要去豫园"}, headers=auth)
print("message", st)
st, saved = call("POST", "/api/v1/plan/%s/save" % sid, {"name": "释放验证"}, headers=auth)
print("save", st)
st, items = call("GET", "/api/v1/trip-items", headers=auth)
print("BEFORE delete:", {k: [r["name"] for r in v] for k, v in items.items() if v})
st, _ = call("DELETE", "/api/v1/itineraries/%s" % iid, headers=auth)
print("delete", st)
st, items = call("GET", "/api/v1/trip-items", headers=auth)
wish = [r for r in items.get("wishlist", [])]
print("AFTER delete wishlist:", [(r["name"], r.get("itinerary_id"), r.get("arranged"), r.get("day")) for r in wish])
print("AFTER delete scheduled:", [r["name"] for r in items.get("scheduled", [])])

import os, sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv(r"D:\CHINATRIP\CHINATRIP CODES\.env")
eng = create_engine(os.environ["DATABASE_URL"])
with eng.connect() as c:
    for r in c.execute(text("select name, status, itinerary_ref, draft_session_id, deletion_flag, arranged from trip_items where owner_device_id=:d"), {"d": DEV}):
        print("DB:", r)
