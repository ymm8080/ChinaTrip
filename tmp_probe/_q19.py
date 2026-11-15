import json, ssl, urllib.request
ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
req = urllib.request.Request("https://127.0.0.1:8443/api/v1/trip-items", headers={"X-Device-ID": "dev-hs4e9vhk"})
with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
    body = json.loads(r.read().decode())
print("board:", {k: [(x["name"], x.get("day"), x.get("itinerary_id")) for x in v] for k, v in body.items() if v})
