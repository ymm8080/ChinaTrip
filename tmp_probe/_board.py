import json, urllib.request
BASE = "http://127.0.0.1:8000"
req = urllib.request.Request(BASE + "/api/v1/trip-items")
req.add_header("X-Device-ID", "dev-hs4e9vhk")
with urllib.request.urlopen(req, timeout=60) as r:
    body = json.loads(r.read().decode("utf-8"))
names = [(k, i["name"], i["status"], i.get("exclusion_flag")) for k, v in body.items() for i in v]
print("total rows:", len(names))
print("颐和园 rows:", [n for n in names if "颐和园" in n[1]])
print("wishlist:", [n[1] for n in names if n[0] == "wishlist"])
print("scheduled:", [n[1] for n in names if n[0] == "scheduled"])
