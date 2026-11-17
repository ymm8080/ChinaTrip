# -*- coding: utf-8 -*-
import json, urllib.request, urllib.error, sys
sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://127.0.0.1:8000"
DEV = "probe-remote-1116b"
PREFS = ("Spend less time planning and more time exploring Beijing on this comprehensive "
         "small-group tour. Over two days, see the highlights of the city, starting with a tour "
         "of Tiananmen Square and the Forbidden City. Then, it's on to see the Great Wall of China "
         "at Mutianyu, walking along the ramparts of the UNESCO World Heritage-listed structure. "
         "On day two, visit the Temple of Heaven, enjoy a rickshaw ride through the old Hutong "
         "district, and conclude the tour at the Summer Palace.")

def req(path, payload=None):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    r = urllib.request.Request(BASE + path, data=data,
        headers={"Content-Type": "application/json", "X-Device-ID": DEV},
        method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(r, timeout=300) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")

st, body = req("/api/v1/plan/start", {"cities": ["北京"], "days": 2, "preferences": PREFS, "start_date": "2026-11-19"})
sid = body.get("session_id")
print("start", st, body.get("state"))
st, body = req(f"/api/v1/plan/{sid}/sites/confirm", {"mandatory": ["天安门广场", "故宫博物院", "慕田峪长城", "天坛", "颐和园"]})
print("confirm", st, body.get("state") if isinstance(body, dict) else str(body)[:200])
st, plan = req(f"/api/v1/plan/{sid}")
p = plan.get("plan") or {}
for d in p.get("days", []):
    print("Day", d.get("day"))
    for it in d.get("items", []):
        print("   ", it.get("start_time"), it.get("end_time"), "|", it.get("name"))
print("VIOLATIONS:", len(plan.get("violations") or []))
for v in (plan.get("violations") or []): print("  !", v)
