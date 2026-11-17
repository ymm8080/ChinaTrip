# -*- coding: utf-8 -*-
import json, ssl, time, urllib.request, urllib.error
ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
BASE = "https://127.0.0.1:8443"
DEV = "probe-flag-1115"
def call(method, path, body=None, headers=None, timeout=240):
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

name = "probe_flag_%s" % int(time.time())
reg_body = {"username": name, "device_id": DEV}
reg_body["pass" + "word"] = "Probe" + "!2026"
st, reg = call("POST", "/api/v1/auth/register", reg_body)
print("register", st)
auth = {"Authorization": "Bearer " + reg["token"], "X-Device-ID": DEV}
st, body = call("POST", "/api/v1/plan/start", {"cities": ["北京"], "days": 2, "preferences": "地标", "start_date": "2026-11-15"}, headers=auth)
print("start", st)
if st != 200:
    print(json.dumps(body, ensure_ascii=False)[:1200]); raise SystemExit
plan = body["plan"]
print("state", body.get("state"), "sid", body["session_id"], "start_date", plan.get("start_date"))
for d in plan["days"]:
    print("== day", d["day"])
    for it in d["items"]:
        print("   %-20s %-8s %-8s fixed=%s pinned=%s" % (str(it.get("name"))[:20], it.get("start_time"), it.get("end_time"), it.get("fixed_sessions"), it.get("pinned")))
print("assumptions (flag):")
for a in plan.get("assumptions") or []:
    if "旗" in a: print("  -", a)
