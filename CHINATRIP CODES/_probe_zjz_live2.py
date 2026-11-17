import json, urllib.request

BASE = "http://127.0.0.1:8000"
DEV = "probe-500fix-1117"

def post(path, payload):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Device-ID": DEV},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode("utf-8"))

brief = "I WANT TO GO TO ZHUJIAZUI ON DEC.02.  LEAVE HOTEL ON 11AM, PLS ARRANGE"
resp = post("/api/v1/plan/start", {
    "preferences": brief,
    "brief": brief,
    "days": 1,
    "cities": [],
    "arrival_date": "2026-12-02",
    "departure_date": "2026-12-03",
    "route_source": "form",
    "lang": "en",
})
print("== probe A2 (route_source=form) ==")
print("state:", resp.get("state"))
print("clarify:", resp.get("clarify"))
print("sites:", resp.get("sites"))
print("reply:", (resp.get("reply") or "")[:240])
blob = json.dumps(resp, ensure_ascii=False)
assert "陆家嘴" not in blob, "LUJIAZUI LEAKED"
print("no lujiazui: OK")
