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
    "cities": [],
    "route_source": "form",
    "lang": "en",
})
print("== probe B (no city, no days) ==")
print("state:", resp.get("state"))
print("clarify:", resp.get("clarify"))
blob = json.dumps(resp, ensure_ascii=False)
assert resp.get("clarify") and len(resp["clarify"]) == 1 and "城市" not in resp["clarify"][0], resp.get("clarify")
assert "哪座城市" not in blob
print("only-days clarify: OK")

brief2 = ("SHANGHAI 2DAY'S TRIP INCLUDING THE BUND, SHANGHAI MUSEUM, "
          "ORITAL TOWER, CURISE, YUGARDEN ZHUJIAZUI")
resp = post("/api/v1/plan/start", {
    "preferences": brief2,
    "brief": brief2,
    "cities": ["上海"],
    "days": 2,
    "route_source": "form",
    "lang": "en",
})
print("== probe C (shanghai brief with ZHUJIAZUI) ==")
print("state:", resp.get("state"))
print("sites:", resp.get("sites"))
blob = json.dumps(resp, ensure_ascii=False)
assert resp.get("sites") and "朱家角古镇" in resp["sites"], resp.get("sites")
assert "陆家嘴" not in blob, "LUJIAZUI LEAKED"
print("zhujiajiao in chips, no lujiazui: OK")
