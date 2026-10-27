# -*- coding: utf-8 -*-
"""预订自动化（booking-auto 三档栈）E2E 测试脚本。

用法（任选其一，均离线零网络）：

    cd "D:/CHINATRIP/CHINATRIP CODES"
    .venv/Scripts/python "../DESIGN/Testing/booking_auto_test_2026-10-28.py"

或 pytest 兼容：.venv/Scripts/python -m pytest "../DESIGN/Testing/booking_auto_test_2026-10-28.py" -q

覆盖面（/api/v1/booking-auto 全部七端点）：
  GET  /tiers     档位目录（L1 恒可用；L2 无 provider key 降级注记；L3 非 ACP 闭环注记）
  POST /select    设备级档位选择 + GET /selected 回读 + 缺设备头 400
  POST /tasks     L1 放票任务（预约名单命中/非命中；start_date 日历算术；缺日期 open_date 留空）
  POST /check     L2 库存语义（名单命中 → official_quota；商业 SKU 无 key → unknown，不编造）
  POST /order-intent  L3 预填下单（authorization_url + handoff 留痕 + requires_user_confirmation）
  GET  /shows /sites  演出/景点目录（PG 不可用 → 503，脚本记 SKIP 不误报）

铁律 22 验证点：L3 永远 requires_user_confirmation=True（支付动作归用户）。
"""

from __future__ import annotations

import sys
from pathlib import Path

_CODES = Path(__file__).resolve().parents[2] / "CHINATRIP CODES"
sys.path.insert(0, str(_CODES))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402
from app.services.reservation_seeds import RESERVATION_V0  # noqa: E402

client = TestClient(create_app())
SEED_NAME = "故宫博物院"
SEED = RESERVATION_V0[SEED_NAME]
RESULTS: list[tuple[str, str, str]] = []  # (case, status, detail)


def record(case: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((case, "PASS" if ok else "FAIL", detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {case}" + (f" — {detail}" if detail else ""))


def skip(case: str, detail: str) -> None:
    RESULTS.append((case, "SKIP", detail))
    print(f"  [SKIP] {case} — {detail}")


def expect(cond: bool, case: str, detail: str = "") -> bool:
    record(case, bool(cond), detail)
    return bool(cond)


# --- 1. 档位目录 ----------------------------------------------------------------

print("\n== GET /booking-auto/tiers ==")
r = client.get("/api/v1/booking-auto/tiers")
tiers = {t["tier"]: t for t in r.json().get("tiers", [])} if r.status_code == 200 else {}
expect(r.status_code == 200 and set(tiers) == {"L1", "L2", "L3"}, "tiers 目录三档齐全")
expect(tiers.get("L1", {}).get("available") is True, "L1 恒可用（零依赖）")
expect(
    tiers.get("L2", {}).get("available") is False and bool(tiers["L2"]["fallback_note"]),
    "L2 无 provider key 降级 L1 且带注记",
    tiers.get("L2", {}).get("fallback_note", "")[:40],
)
# L3 含 L2 能力（rank>=2 同一门槛）：无 key 时 effective=L1 + 降级注记；有 key 才是 L3
expect(
    tiers.get("L3", {}).get("effective") in ("L1", "L3")
    and bool(tiers["L3"]["fallback_note"]),
    "L3 档注记存在（无 key 时 effective=L1）",
    f"effective={tiers.get('L3', {}).get('effective')}",
)

# --- 2. 档位选择（设备记忆） ------------------------------------------------------

print("\n== POST/GET /booking-auto/select|selected ==")
r = client.post("/api/v1/booking-auto/select", json={"tier": "L2"})
expect(r.status_code == 400, "缺 X-Device-ID → 400 missing_device_id")
r = client.post("/api/v1/booking-auto/select", json={"tier": "L2"}, headers={"X-Device-ID": "e2e-bk"})
expect(r.status_code == 200 and r.json()["tier"] == "L2", "select 记住 L2")
r = client.get("/api/v1/booking-auto/selected", headers={"X-Device-ID": "e2e-bk"})
expect(r.status_code == 200 and r.json()["tier"] == "L2", "selected 回读 L2")
r = client.post("/api/v1/booking-auto/select", json={"tier": "L9"}, headers={"X-Device-ID": "e2e-bk"})
expect(r.status_code == 422, "非法档位 L9 → 422")

# --- 3. L1 放票任务 ---------------------------------------------------------------

print("\n== POST /booking-auto/tasks ==")
visits = [
    {"name": SEED_NAME, "city": "北京", "day": 3},
    {"name": "外滩", "city": "上海", "day": 2},  # 不在预约名单 → 不生成任务
]
r = client.post("/api/v1/booking-auto/tasks", json={"visits": visits, "start_date": "2026-11-01"})
tasks = r.json().get("tasks", [])
expect(r.status_code == 200 and len(tasks) == 1, "名单命中 1 条、非命中过滤", f"tasks={len(tasks)}")
t = tasks[0]
expect(t["name"] == SEED_NAME and t["city"] == "北京", "任务字段透传 name/city")
expect(t["visit_date"] == "2026-11-03", "visit_date = start_date + (day-1)", t["visit_date"])
expect(
    t["advance_days"] == SEED["days"] and t["release_time"] == SEED.get("release", "00:00"),
    "advance_days/release_time 与种子一致",
    f"{t['advance_days']}d {t['release_time']}",
)
from datetime import date, timedelta

_expected_open = (date(2026, 11, 1) + timedelta(days=3 - 1 - SEED["days"])).isoformat()
expect(t["open_date"] == _expected_open, "open_date = visit_date - advance_days", str(t["open_date"]))
r = client.post("/api/v1/booking-auto/tasks", json={"visits": visits})
expect(
    r.status_code == 200 and r.json()["tasks"][0]["open_date"] is None,
    "缺 start_date：任务保留、open_date 留空",
)

# --- 4. L2 库存语义 ----------------------------------------------------------------

print("\n== POST /booking-auto/check ==")
r = client.post("/api/v1/booking-auto/check", json={"name": SEED_NAME, "city": "北京", "visit_date": "2026-11-03"})
expect(
    r.status_code == 200 and r.json()["availability"] == "official_quota",
    "预约名单命中 → official_quota（不查渠道、不编造）",
)
r = client.post("/api/v1/booking-auto/check", json={"name": "北京环球影城", "city": "北京", "visit_date": "2026-11-03"})
expect(
    r.status_code == 200 and r.json()["availability"] == "unknown",
    "商业 SKU 无 provider key → 诚实 unknown",
)

# --- 5. L3 下单意图（铁律 22） ------------------------------------------------------

print("\n== POST /booking-auto/order-intent ==")
# L3 含 L2 能力：无 provider key 时 resolve 降级 L1（与 /tiers 目录一致）
from app.config import get_settings  # noqa: E402

_s = get_settings()
_l3_expected = (
    "L3"
    if any(
        (
            _s.ctrip_union_api_key,
            _s.tongcheng_api_key,
            _s.meituan_api_key,
            _s.klook_api_key,
            _s.tripcom_api_key,
        )
    )
    else "L1"
)
r = client.post("/api/v1/booking-auto/order-intent", json={"name": SEED_NAME, "city": "北京", "tier": "L3"})
body = r.json() if r.status_code == 200 else {}
expect(r.status_code == 200, "order-intent 200")
expect(body.get("tier_used") == _l3_expected, "tier_used 符合档位解析（无 key 降 L1）", str(body.get("tier_used")))
expect(body.get("requires_user_confirmation") is True, "铁律 22：requires_user_confirmation=True")
expect(bool(body.get("authorization_url")), "authorization_url 非空", body.get("authorization_url", "")[:60])
expect(isinstance(body.get("handoff_id"), str) and body["handoff_id"], "handoff 留痕已落（opened）")
expect(body.get("geo_channel") in ("meituan", "tripcom", None), "geo 分流字段存在", str(body.get("geo_channel")))
r = client.post("/api/v1/booking-auto/order-intent", json={"name": SEED_NAME, "tier": "L9"})
expect(r.status_code == 422, "非法档位 → 422")

# --- 6. 演出/景点目录（PG 可用性相关，503 → SKIP） -----------------------------------

print("\n== GET /booking-auto/shows|sites ==")
for kind in ("shows", "sites"):
    r = client.get(f"/api/v1/booking-auto/{kind}?city=北京&limit=5")
    if r.status_code == 200:
        cards = r.json().get("shows", [])
        ok = isinstance(cards, list) and all("name" in c and "has_direct" in c for c in cards)
        expect(ok, f"{kind} 目录 200（{len(cards)} 条，结构合法）")
    elif r.status_code == 503:
        skip(f"{kind} 目录", "PG 底库不可达（本机未起 docker db），503 诚实失败符合设计")
    else:
        record(f"{kind} 目录", False, f"意外状态码 {r.status_code}")

# --- 汇总 --------------------------------------------------------------------------

fails = [x for x in RESULTS if x[1] == "FAIL"]
passes = [x for x in RESULTS if x[1] == "PASS"]
skips = [x for x in RESULTS if x[1] == "SKIP"]
print(f"\n==== 汇总：{len(passes)} PASS / {len(fails)} FAIL / {len(skips)} SKIP ====")
if fails:
    for case, _, detail in fails:
        print(f"  FAIL {case}: {detail}")
    sys.exit(1)
print("ALL GREEN" if not skips else "ALL GREEN（含可接受 SKIP）")
