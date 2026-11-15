"""5-min driver for restaurant photos (2026-11-14, registered as schtask).

Per run:
  1. DB fingerprint gate (no writes unless 5432 is the prod DB).
  2. amap pool probe (1 around call):
       alive  -> run backfill_restaurant_photos --limit 500 --concurrency 2
       10044  -> skip (pool drained)
       error  -> unknown, skip this run
  3. Commons+og ingest --limit 120 (HTTP-only, fill-empty-only, self-skips
     cooldown rows — targets=0 after a full pass).
  4. Count remaining amap-viable rows (active + CJK name + no photo +
     outside cooldown). Ledger line only when something filled or state
     changed.
  5. COMPLETE when remaining == 0 AND amap pool dead: nothing more can be
     fetched today -> print marker, exit 3 (the .cmd wrapper deletes the
     schtask on exit code 3).

Lock: .night_photos_lock fresh (<12 min) -> skip run (anti-overlap).
00:00 guard: between 23:55-00:10 skip the amap lane (the ONCE race task
owns that window).
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
LOCK = REPO / ".night_photos_lock"
LOG = REPO / "ops" / "night_photos_driver.log"
LEDGER = REPO / "ops" / "p1_data_tasks_progress.md"
VENV_PY = REPO / ".venv" / "Scripts" / "python.exe"


def log(line: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {line}\n")


def ledger(line: str) -> None:
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def fingerprint_ok() -> bool:
    r = subprocess.run(
        [str(VENV_PY), "ops/db_fingerprint.py"],
        cwd=REPO, capture_output=True,
    )
    return r.returncode == 0


def amap_probe() -> str:
    """alive / dead / unknown."""
    from app.config import get_settings

    params = {
        "key": get_settings().amap_api_key,
        "keywords": "南京晶丽酒店",
        "location": "118.78,32.06",
        "radius": "3000",
        "page_size": "5",
        "show_fields": "business,photos",
        "output": "JSON",
    }
    for _ in range(2):  # 网络抖动重试一次
        try:
            r = httpx.get(
                "https://restapi.amap.com/v5/place/around",
                params=params, timeout=10,
            )
            d = r.json()
            if d.get("status") == "1":
                return "alive"
            if "OVER_LIMIT" in str(d.get("info") or ""):
                return "dead"
            return "unknown"
        except Exception:
            time.sleep(2)
    return "unknown"


def run_batch(cmd: list[str], timeout: int = 1500) -> dict:
    try:
        r = subprocess.run(cmd, cwd=REPO, capture_output=True, timeout=timeout, text=True)
        out = (r.stdout or "").strip().splitlines()
        for line in reversed(out):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except ValueError:
                    continue
        return {"rc": r.returncode}
    except subprocess.TimeoutExpired:
        return {"rc": "timeout"}


def db_counts() -> dict:
    import psycopg

    conn = psycopg.connect("postgresql://chinatrip:chinatrip@localhost:5432/chinatrip")
    cur = conn.cursor()
    cur.execute(
        "SELECT count(*) FILTER (WHERE photos IS NOT NULL), count(*) "
        "FROM restaurants WHERE status='active'"
    )
    n, total = cur.fetchone()
    cur.execute(
        "SELECT count(*) FROM restaurants WHERE status='active' AND photos IS NULL "
        "AND name_zh ~ '[一-龥]' AND name_zh <> '' "
        "AND (photos_fetched_at IS NULL OR photos_fetched_at < now() - interval '24 hours')"
    )
    remaining = cur.fetchone()[0]
    conn.close()
    return {"with_photos": n, "total": total, "remaining": remaining}


def main() -> int:
    # lock
    if LOCK.exists() and time.time() - LOCK.stat().st_mtime < 720:
        log("lock fresh, skip")
        return 0
    LOCK.write_text(str(time.time()))

    try:
        if not fingerprint_ok():
            log("fingerprint FAIL - no writes")
            ledger(f"{datetime.now():%Y-%m-%d %H:%M} 餐厅照片driver：指纹闸FAIL，本轮禁写")
            return 0

        before = db_counts()
        log(f"before: {json.dumps(before)}")

        # amap lane (skip 23:55-00:10 — the ONCE race owns that window)
        hhmm = datetime.now().strftime("%H%M")
        amap_state = "skipped_race_window"
        amap_stats: dict = {}
        if not (2355 <= int(hhmm) <= 2400 or 0 <= int(hhmm) <= 10):
            amap_state = amap_probe()
            if amap_state == "alive":
                amap_stats = run_batch(
                    [str(VENV_PY), "-m", "app.jobs.backfill_restaurant_photos",
                     "--limit", "500", "--concurrency", "2"]
                )
                log(f"amap batch: {json.dumps(amap_stats)}")

        # commons lane (always; self-skips cooldown rows)
        commons_stats = run_batch(
            [str(VENV_PY), "ops/ingest_restaurant_photos_commons.py", "--limit", "120"],
            timeout=900,
        )
        log(f"commons: {json.dumps(commons_stats)}")

        after = db_counts()
        filled = after["with_photos"] - before["with_photos"]
        log(f"after: {json.dumps(after)}")

        if filled > 0 or amap_state == "alive":
            ledger(
                f"{datetime.now():%Y-%m-%d %H:%M} 餐厅照片driver：有图 "
                f"{before['with_photos']}→{after['with_photos']}/{after['total']}，"
                f"剩余可试 {after['remaining']}，amap={amap_state}，"
                f"amap_batch={json.dumps(amap_stats)}，commons={json.dumps(commons_stats)}"
            )

        # completion: no amap-viable rows left AND pool dead
        if after["remaining"] == 0 and amap_state == "dead":
            ledger(
                f"{datetime.now():%Y-%m-%d %H:%M} 餐厅照片收口：免费源全量试完且 amap 池死——"
                f"driver 自删任务收口（有图 {after['with_photos']}/{after['total']}）"
            )
            log("COMPLETE")
            return 3
        return 0
    finally:
        try:
            LOCK.unlink(missing_ok=True)
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
