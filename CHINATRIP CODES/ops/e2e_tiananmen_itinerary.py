# -*- coding: utf-8 -*-
"""行程中心真机 E2E：载入已存行程 → 保存 → 详情页验证天安门旗时。"""
import json, sys, urllib.request

BASE = "http://127.0.0.1:8000"
DEVICE = "dev-hs4e9vhk"       # 用户真实设备（会话实证）
ITID = "it-f84ab5be"          # 用户正在编辑的行程


def req(path, payload=None, timeout=420):
    data = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json", "X-Device-ID": DEVICE},
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", "replace")
        try:
            return resp.status, json.loads(body)
        except Exception:
            return resp.status, body


def tiananmen(plan):
    for d in plan.get("days") or []:
        for it in d.get("items") or []:
            n = str(it.get("name") or "")
            if "天安门" in n and "广场" in n:
                return d.get("day"), it
    return None, None


# 1) ✏️ 修改：载入已存行程
st, body = req(f"/api/v1/plan/from-itinerary/{ITID}", {})
print("load http:", st)
plan = (body.get("plan") or (body.get("session") or {}).get("plan") or {})
sid = body.get("session_id") or (body.get("session") or {}).get("session_id")
print("session:", sid, "| plan.start_date:", plan.get("start_date"))
d, it = tiananmen(plan)
print("loaded day:", d, "| start:", (it or {}).get("start_time"),
      "| fixed:", (it or {}).get("fixed_sessions"))
assert it and str(it.get("start_time", ""))[:5] == "07:08", (
    f"load 后仍非旗时: {it and it.get('start_time')}")

# 2) 💾 保存（把纠正后的计划写回行程库，重建详情行）
st, saved = req(f"/api/v1/plan/{sid}/save", {"start_date": plan.get("start_date")})
print("save http:", st)

# 3) 详情页（PG 行）核对
st, detail = req(f"/api/v1/itineraries/{ITID}/detail")
print("detail http:", st)
hit = None
for day in detail.get("days") or []:
    for it in day.get("items") or []:
        n = str(it.get("name") or "")
        if "天安门" in n and "广场" in n:
            hit = (day.get("day"), it.get("start_time"))
print("detail hit:", hit)
assert hit and str(hit[1])[:5] == "07:08", f"详情行仍非旗时: {hit}"
print("ITINERARY E2E PASS: 行程中心详情行 天安门 == 07:08")
