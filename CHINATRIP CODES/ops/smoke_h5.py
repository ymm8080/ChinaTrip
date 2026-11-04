# -*- coding: utf-8 -*-
"""chinatrip H5 smoke check - post-restart gate (created 2026-11-03, http_500 incident).

Default: health + /h5/ static page per port (zero LLM cost).
--full:  also drives one real plan/start -> main-lane message -> fast-lane
         message (one throwaway plan session, ~1 minute). Exercises exactly
         the lanes that returned HTTP 500 while /health stayed 200 on
         2026-11-03 - /health alone is NOT a health proof.

Usage:
    python ops/smoke_h5.py                      # default port 8000
    python ops/smoke_h5.py --ports 8000 8443
    python ops/smoke_h5.py --ports 8000 --full
Exit 0 = all checks PASS, 1 = any FAIL.
"""
import argparse
import json
import ssl
import sys
import urllib.error
import urllib.request

DEVICE = "probe-smoke"


def req(base, path, payload=None, timeout=180):
    url = base + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    r = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "X-Device-ID": DEVICE},
        method="POST" if data is not None else "GET",
    )
    ctx = ssl._create_unverified_context() if url.startswith("https") else None
    try:
        with urllib.request.urlopen(r, timeout=timeout, context=ctx) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001 - report as failure, never crash
        return -1, repr(e)


def smoke_port(port, full=False):
    base = f"http://127.0.0.1:{port}" if port != 8443 else f"https://127.0.0.1:{port}"
    checks = {}
    st, _ = req(base, "/health")
    checks["health"] = st == 200
    st, _ = req(base, "/h5/")
    checks["static"] = st in (200, 307)
    if full:
        st, body = req(
            base,
            "/api/v1/plan/start",
            {"cities": ["上海", "西安"], "days": 5, "start_date": "2026-11-09"},
        )
        checks["plan_start"] = st == 200
        sid = None
        if st == 200:
            try:
                sid = json.loads(body).get("session_id")
            except Exception:
                pass
        if sid:
            st, _ = req(base, f"/api/v1/plan/{sid}/message", {"text": "帮我看看整体行程"})
            checks["message_main"] = st == 200
            st, _ = req(base, f"/api/v1/plan/{sid}/message", {"text": "帮我看看天气"})
            checks["message_fast"] = st == 200
        else:
            checks["message_main"] = False
            checks["message_fast"] = False
    ok = all(checks.values())
    print(f"port {port}: {'PASS' if ok else 'FAIL'} {checks}", flush=True)
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ports", type=int, nargs="+", default=[8000])
    ap.add_argument("--full", action="store_true")
    a = ap.parse_args()
    oks = [smoke_port(p, a.full) for p in a.ports]
    sys.exit(0 if all(oks) else 1)


if __name__ == "__main__":
    main()
