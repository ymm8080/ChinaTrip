# -*- coding: utf-8 -*-
"""diag: 碑林双卡修复活服冒烟——西安4天必去碑林博物馆，验证吸收进族卡."""
import json
import pathlib
import sys
import urllib.request

BASE = "http://localhost:8000/api/v1"
DEV = "smoke-beilin-1107b"


def _post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Device-ID": DEV},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _site_names(sites):
    names = []
    for s in sites or []:
        names.append(s.get("name") if isinstance(s, dict) else str(s))
    return names


def main() -> int:
    body = _post(
        "/plan/start",
        {
            "cities": ["西安"],
            "days": 4,
            "preferences": "必去：钟楼、鼓楼、回民街、碑林博物馆",
            "start_date": "2026-11-09",
            "lang": "zh",
        },
    )
    sid = body.get("session_id")
    state = body.get("state")
    print("session:", sid, "state:", state, flush=True)
    if state == "site_confirm":
        names = _site_names(body.get("sites"))
        print("site_confirm:", names, flush=True)
        body = _post(f"/plan/{sid}/sites/confirm", {"mandatory": names})
        state = body.get("state")
        print("after confirm state:", state, flush=True)
    plan = body.get("plan") or {}
    out = pathlib.Path(__file__).with_name("diag_beilin_smoke2_resp.json")
    out.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
    standalone = []
    chips = []
    for day in plan.get("days", []):
        for it in day.get("items", []):
            nm = it.get("name") or ""
            if "碑林" in nm or "城墙" in nm or "钟楼" in nm or "鼓楼" in nm:
                row = (day["day"], nm, it.get("poi_id"), it.get("category"))
                standalone.append(row)
            for st in it.get("stops") or []:
                if any(k in (st.get("name") or "") for k in ("碑林", "城墙", "钟楼", "鼓楼")):
                    chips.append((day["day"], it.get("name"), st.get("name")))
    print("=== 相关主卡 ===", flush=True)
    for r in standalone:
        print("  day%s %s poi=%s cat=%s" % r, flush=True)
    print("=== 族卡子站 chips ===", flush=True)
    for r in chips:
        print("  day%s 主卡[%s] chip[%s]" % r, flush=True)
    for a in body.get("assumptions") or []:
        if "碑林" in a or "同街" in a or "互替" in a or "合并" in a:
            print("ASSUMPTION:", a, flush=True)
    museum_standalone = {r[0] for r in standalone if "碑林博物馆" in r[1]}
    scenic_days = {r[0] for r in standalone if "城墙·碑林" in r[1]}
    museum_chip_days = {
        d for d, _main, chip in chips if "碑林博物馆" in (chip or "")
    }
    if museum_standalone and (museum_standalone & scenic_days):
        print("VERDICT: 同日双卡捆绑（两卡同日成线）", flush=True)
    elif museum_chip_days and (museum_chip_days & scenic_days):
        print("VERDICT: 同日捆绑成线（伞名主卡+博物馆子站同卡）", flush=True)
    elif museum_standalone or museum_chip_days:
        print("VERDICT: 碑林站出现但与伞名行跨日（FAIL）", flush=True)
    else:
        print("VERDICT: 碑林站未出现（需查选择层）", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
