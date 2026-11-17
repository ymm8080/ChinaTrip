import json, time, urllib.request

BASE = "http://127.0.0.1:8000"
DEV = "probe-500fix-1117"

def post(path, payload, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(
                BASE + path,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "X-Device-ID": DEV},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as exc:
            print(f"  attempt {i+1} failed: {exc}")
            time.sleep(6)
    raise SystemExit("all attempts failed")

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
print("state:", resp.get("state"))
print("sites:", resp.get("sites"))
blob = json.dumps(resp, ensure_ascii=False)
assert resp.get("sites") and "朱家角古镇" in resp["sites"], resp.get("sites")
assert "陆家嘴" not in blob, "LUJIAZUI LEAKED"
print("zhujiajiao in chips, no lujiazui: OK")
