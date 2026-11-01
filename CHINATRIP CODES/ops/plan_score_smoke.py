# -*- coding: utf-8 -*-
"""行程全局评分冒烟工具（S3 指标面板 CLI v1）。

用法：
  python ops/plan_score_smoke.py                # 重放 5 天沪-西安案并打分
  python ops/plan_score_smoke.py <session_id>   # 给 h5_state.db 里的既存会话行程打分

评分口径见 app/services/itinerary/scoring.py（硬=untimed/空白上午/违规；
软=雨暴露/预算溢出/转场/午餐漂移/日均衡）。退出码 0=硬惩罚全零。
"""

import json
import sqlite3
import sys
import urllib.request

sys.path.insert(0, r"D:\CHINATRIP\CHINATRIP CODES")
sys.stdout.reconfigure(encoding="utf-8")

from app.services.itinerary.scoring import score_payload  # noqa: E402

STATE_DB = r"D:\CHINATRIP\CHINATRIP CODES\data\h5_state.db"
BASE = "http://127.0.0.1:8000/api/v1"
RAIN = {"西安": {3, 4}}  # 沪-西安 5 天案（10-31 出发）的雨日口径


def show(tag, payload):
    sc = score_payload(payload, rain_days=RAIN)
    print(f"== {tag} ==")
    print("  summary:", sc.summary())
    print("  counts :", json.dumps(sc.counts, ensure_ascii=False))
    for d in payload.get("days", []):
        names = [
            (it.get("name") or it.get("mode") or "?", it.get("start_time"))
            for it in d.get("items", [])
        ]
        print(f"  day{d.get('day')} {d.get('base_city')}: {names}")
    return sc


def score_session(session_id: str):
    db = sqlite3.connect(STATE_DB)
    row = db.execute(
        "SELECT payload FROM plan_sessions WHERE session_id=?", (session_id,)
    ).fetchone()
    if not row:
        print(f"session {session_id} not found")
        sys.exit(2)
    show(f"session {session_id[:8]}", json.loads(row[0])["plan"])


def replay():
    hdr = {"Content-Type": "application/json", "X-Device-ID": "ops-score-smoke"}

    def call(method, path, payload=None):
        req = urllib.request.Request(
            BASE + path,
            method=method,
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            headers=hdr,
        )
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode("utf-8"))

    r = call(
        "POST",
        "/plan/start",
        {
            "cities": ["上海", "西安", "上海"],
            "days": 5,
            "city_days": {"西安": 4, "上海": 1},
            "start_date": "2026-10-31",
        },
    )
    sid = r["session_id"]
    if r.get("state") == "clarify":
        r = call("POST", f"/plan/{sid}/message", {"text": "偏好：无特别要求"})
    for _ in range(3):
        if r.get("plan"):
            break
        if r.get("state") == "resto_confirm":
            r = call("POST", f"/plan/{sid}/message", {"text": "餐厅都可以"})
            continue
        break
    return show(f"replay {sid[:8]}", r["plan"])


def main():
    if len(sys.argv) > 1:
        score_session(sys.argv[1])
        return
    sc = replay()
    sys.exit(0 if sc.ok else 1)


if __name__ == "__main__":
    main()
