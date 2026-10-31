"""演出场次时间刷新 pipeline（2026-10-31 建，每周日晚自动化喂给它）。

输入：ops/show_sessions_updates.json  {"name_zh": "session_time", ...}
动作：
  1. 校验标记前缀——必须以 仅夜场/傍晚/夜场为主/夜间街区演艺/多场/全天/
     日场/场次随排期 之一开头（_show_night_only 的分桶契约，plan.py:230）；
  2. 备份 04 CSV 到 _src/（带日期后缀）；
  3. 更新 CSV session_time 列（utf-8-sig + CRLF 保持）；
  4. 更新 DB source='show' 行的 opening_hours（按名称包含匹配，值变化才写）；
  5. 打印 JSON 变更摘要。
默认 dry-run（只打印 diff）；--apply 才落盘。
"""

from __future__ import annotations

import csv
import io
import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CSV_PATH = REPO / "DESIGN" / "POIS DATASOURCE" / "04_演艺演出_主要旅游城市.csv"
SRC_DIR = REPO / "DESIGN" / "POIS DATASOURCE" / "_src"
UPDATES_PATH = Path(__file__).resolve().parent / "show_sessions_updates.json"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MARKERS = (
    "仅夜场",
    "傍晚",
    "夜场为主",
    "夜间街区演艺",
    "多场",
    "全天",
    "日场",
    "场次随排期",
)


def _load_updates() -> dict[str, str]:
    if not UPDATES_PATH.exists():
        print(json.dumps({"error": f"no updates file: {UPDATES_PATH}"}))
        raise SystemExit(1)
    raw = json.loads(UPDATES_PATH.read_text(encoding="utf-8"))
    bad = {k: v for k, v in raw.items() if not str(v).startswith(MARKERS)}
    if bad:
        print(
            json.dumps(
                {"error": "marker prefix missing (plan.py contract)", "rows": bad},
                ensure_ascii=False,
            )
        )
        raise SystemExit(1)
    return raw


def main(apply: bool) -> None:
    updates = _load_updates()
    with io.open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if "session_time" not in fields:
        fields.append("session_time")

    changed_csv: dict[str, dict] = {}
    for r in rows:
        new = updates.get(r["name_zh"])
        if new is None or r.get("session_time") == new:
            continue
        changed_csv[r["name_zh"]] = {"old": r.get("session_time", ""), "new": new}
        r["session_time"] = new

    if apply:
        if changed_csv:
            SRC_DIR.mkdir(exist_ok=True)
            backup = SRC_DIR / (
                f"04_演艺演出_主要旅游城市.session_time_{date.today():%Y-%m-%d}.backup.csv"
            )
            if not backup.exists():
                with io.open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
                    backup.write_text(f.read(), encoding="utf-8", newline="")
        with io.open(CSV_PATH, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)

    # DB 同步（source='show' 行，名称包含匹配 CSV 名或反向）
    db_changed: dict[str, dict] = {}
    if apply and changed_csv:
        from sqlalchemy import select

        from app.db import get_session_factory
        from app.models import Poi

        s = get_session_factory()()
        for p in s.execute(select(Poi).where(Poi.source == "show")).scalars().all():
            name = p.name_zh or ""
            key = next(
                (k for k in changed_csv if k.strip("《》") in name or name in k),
                None,
            )
            if key is None:
                continue
            new = changed_csv[key]["new"]
            if (p.opening_hours or "") != new:
                db_changed[name] = {"old": p.opening_hours, "new": new}
                p.opening_hours = new
        s.commit()

    detail: dict = changed_csv if not apply else {}
    if apply:
        detail = {"csv": changed_csv, "db": db_changed}
    print(
        json.dumps(
            {
                "updates_in_file": len(updates),
                "csv_changed": len(changed_csv),
                "db_changed": len(db_changed),
                "applied": apply,
                "detail": detail,
            },
            ensure_ascii=False,
            indent=1,
        )
    )


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
