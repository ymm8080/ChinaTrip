import json, ssl, urllib.request
ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(path, dev):
    req = urllib.request.Request("https://127.0.0.1:8443"+path, headers={"X-Device-ID": dev})
    with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
        return json.loads(r.read().decode())
items = get("/api/v1/trip-items", "probe-wishdel-1114")
print("probe device board:", {k: [x["name"] for x in v] for k, v in items.items() if v})
