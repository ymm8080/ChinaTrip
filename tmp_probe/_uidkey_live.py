# -*- coding: utf-8 -*-
import json, ssl, time, urllib.request
ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
BASE = "https://127.0.0.1:8443"
DEV = "probe-uidkey-1114"
TOK = None

def call(method, path, body=None, headers=None, timeout=150):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            raw = r.read().decode("utf-8"); return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try: return e.code, json.loads(raw)
        except Exception: return e.code, raw

# 1) register a probe account (idempotent-ish: unique name)
name = "probe_uidkey_%s" % int(time.time())
st, reg = call("POST", "/api/v1/auth/register", {"username": name, "password": "probe-pass-123", "device_id": DEV})
print("register", st, str(reg)[:60])
TOK = reg.get("token")
auth = {"Authorization": "Bearer " + TOK}

# 2) plan start with account
st, body = call("POST", "/api/v1/plan/start", {"cities": ["上海"], "days": 1, "preferences": "地标"}, headers={**auth, "X-Device-ID": DEV})
print("start", st, body.get("state"))
sid, iid = body.get("session_id"), (body.get("plan") or {}).get("itinerary_id")

# 3) chat wish
st, body = call("POST", "/api/v1/plan/%s/message" % sid, {"text": "我要去豫园"}, headers={**auth, "X-Device-ID": DEV})
print("message", st, str(body.get("reply"))[:50])

# 4) save (stamps account on committed rows)
st, saved = call("POST", "/api/v1/plan/%s/save" % sid, {"name": "uid-key验证"}, headers={**auth, "X-Device-ID": DEV})
print("save", st)

# 5) board WITHOUT auth from ANOTHER device -> should NOT see (owned by DEV, account mine)
st, items = call("GET", "/api/v1/trip-items", headers={"X-Device-ID": "other-device-1114"})
print("board from other device (no auth):", {k: [r["name"] for r in v] for k, v in items.items() if v})

# 6) board WITH account from ANOTHER device -> should see (USER ID key)
st, items = call("GET", "/api/v1/trip-items", headers={**auth, "X-Device-ID": "other-device-1114"})
print("board from other device (with account):", {k: [r["name"] for r in v] for k, v in items.items() if v})

# 7) DB check
import os, sys
sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv(r"D:\CHINATRIP\CHINATRIP CODES\.env")
eng = create_engine(os.environ["DATABASE_URL"])
with eng.connect() as c:
    for r in c.execute(text("select name, owner_device_id, owner_account_id, draft_session_id, deletion_flag from trip_items where owner_device_id=:d"), {"d": DEV}):
        print("DB:", r)
