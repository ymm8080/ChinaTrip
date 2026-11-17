# -*- coding: utf-8 -*-
"""天安门旗时 E2E（真实 HTTP 服务，2026-11-14 UAT 验收）。

场景复刻用户操作：H5 行前信息默认开始/结束 08:30/21:30 + 北京 2 天
+ 出发日期 2026-11-25 + 点名天安门广场 → 取回真实 plan，断言卡片
start_time = 当日升旗 07:10（数据库真值）。

用法：python tmp_flag_table/e2e_tiananmen.py [--port 8000]
"""
import argparse
import json
import sys
import time as _time
import urllib.request

DEVICE = "probe-e2e-flag"


def req(base, path, payload=None, timeout=420):
    url = base + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    r = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "X-Device-ID": DEVICE},
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8", "replace"))


def find_tiananmen(plan):
    for day in plan.get("days") or []:
        for it in day.get("items") or []:
            name = str(it.get("name") or "")
            if "天安门" in name and "广场" in name:
                return day.get("day"), it
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    base = f"http://127.0.0.1:{args.port}"

    # 1) 真实表单：行前信息默认起止 08:30/21:30（用户附加信息窗）
    st, body = req(base, "/api/v1/plan/start", {
        "cities": ["北京"],
        "days": 2,
        "preferences": "历史文化，想去天安门广场看升旗",
        "start_date": "2026-11-25",
        "arrival_time": "08:30",
        "departure_time": "21:30",
        "intake": True,
    })
    assert st == 200, f"plan/start http {st}: {body}"
    sid = body.get("session_id") or (body.get("session") or {}).get("session_id")
    assert sid, f"no session_id: {body}"
    print("session:", sid)

    # 2) 确保天安门在册：一句话心愿（走快语心愿/主车道），幂等
    plan = body.get("plan") or (body.get("session") or {}).get("plan") or {}
    day_no, item = find_tiananmen(plan)
    if item is None:
        st, msg = req(base, f"/api/v1/plan/{sid}/message", {"text": "我要去天安门广场"})
        print("message http:", st)
        st, full = req(base, f"/api/v1/plan/{sid}")
        assert st == 200, f"get plan http {st}"
        plan = full.get("plan") or full
        day_no, item = find_tiananmen(plan)

    # 3) 断言：旗时 = 2026-11-25 升旗 07:10
    assert item is not None, "天安门广场 not in plan"
    print("day:", day_no)
    print("start:", item.get("start_time"), "| end:", item.get("end_time"))
    print("fixed:", item.get("fixed_sessions"), "| pinned:", item.get("pinned"))
    assert str(item.get("start_time", ""))[:5] == "07:10", (
        f"EXPECTED 07:10, GOT {item.get('start_time')} "
        f"(fixed={item.get('fixed_sessions')}, pinned={item.get('pinned')})"
    )
    print("E2E PASS: 天安门 start_time == 07:10 (2026-11-25 升旗)")


if __name__ == "__main__":
    sys.exit(main())
