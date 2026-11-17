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
auth = {"Authorization": "Bearer " + reg["token"], "X-Device-ID": DEV}

variants = [
    {"cities": ["北京"], "days": 2, "preferences": "我要去天安门广场看升旗", "start_date": "2026-11-15"},
    {"cities": [], "days": 0, "preferences": "北京 2 天，想去天安门广场", "start_date": "2026-11-15"},
]
for i, req_body in enumerate(variants):
    st, body = call("POST", "/api/v1/plan/start", req_body, headers=auth)
    print("=" * 70)
    print("variant", i, "start", st, "state", body.get("state") if st == 200 else body)
    if st != 200: continue
    plan = body["plan"]
    print("start_date", plan.get("start_date"), "assumptions_flag", [a for a in plan.get("assumptions") or [] if "旗" in a])
    for d in plan["days"]:
        for it in d["items"]:
            nm = str(it.get("name"))
            if "天安门" in nm or "tiananmen" in nm.lower():
                print("   HIT day%d %-22s %s-%s fixed=%s pinned=%s dur=%s" % (d["day"], nm, it.get("start_time"), it.get("end_time"), it.get("fixed_sessions"), it.get("pinned"), it.get("duration_minutes")))
