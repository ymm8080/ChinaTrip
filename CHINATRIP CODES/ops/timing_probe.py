"""progress_probe 作业体（timing_engine 调用）：PROGRESS 待办计数。

读 DESIGN/planning_engine_upgrade_PROGRESS.md，统计未勾选待办行
（「- [ ]」开头），写 data/dev_pending.flag：
    {"pending": N, "checked_at": ISO, "has_pending": bool}
LLM 巡检层/外部观测读这个标志即可判断开发是否收尾。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # CHINATRIP CODES/
PROGRESS = ROOT.parent / "DESIGN" / "planning_engine_upgrade_PROGRESS.md"
FLAG = ROOT / "data" / "dev_pending.flag"


def count_pending(text: str) -> int:
    """未勾选待办行数：「- [ ]」；blocked 行（含「blocked」）不计。"""
    n = 0
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("- [ ]") and "blocked" not in s.lower():
            n += 1
    return n


def main() -> int:
    try:
        text = PROGRESS.read_text(encoding="utf-8")
    except OSError:
        text = ""
    pending = count_pending(text)
    payload = {
        "pending": pending,
        "has_pending": pending > 0,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        # 明细首 5 条（观测用）
        "sample": [
            ln.strip()[6:].strip()
            for ln in text.splitlines()
            if ln.strip().startswith("- [ ]") and "blocked" not in ln.lower()
        ][:5],
    }
    FLAG.parent.mkdir(parents=True, exist_ok=True)
    FLAG.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
