"""5432 指纹闸：确认应答 localhost:5432 的是生产库（Docker postgis 16）。

2026-11-04 夜间事故：Docker Desktop 挂掉后，WSL 原生 PostgreSQL 18 自启
抢占 5432，H5（8000/8443）与并行作业静默连到 10-29 旧快照（pois 总量
仅 4.7k、hours_source='amap'=0），没有任何报错。本闸在 db_up 之后跑，
按 pois 行数判别——低于阈值即打 CRITICAL 并以 rc=2 退出（调用方可以选择
据此熔断；现存调用方不检查 rc，但日志必须醒目）。

阈值口径：生产库 pois ≥ 10,000（2026-11 实况 ~14.5k）；旧 WSL 快照
~4.7k，留足余量。

用法（一般由 ops/db_up.cmd 代跑）：
    python ops/db_fingerprint.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text  # noqa: E402

from app.config import get_settings  # noqa: E402

MIN_PRODUCTION_POIS = 10_000


def main() -> int:
    url = get_settings().database_url
    stamp = f"[{datetime.now():%Y-%m-%d %H:%M:%S}]"
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 5})
        with engine.connect() as conn:
            total = conn.execute(text("SELECT count(*) FROM pois")).scalar()
            amap = conn.execute(
                text("SELECT count(*) FROM pois WHERE hours_source='amap'")
            ).scalar()
        engine.dispose()
    except Exception as exc:  # noqa: BLE001 — 指纹失败也要留痕
        print(f"{stamp} CRITICAL db_fingerprint: 指纹查询失败 {type(exc).__name__}: {str(exc)[:120]}")
        return 3
    if total is None or total < MIN_PRODUCTION_POIS:
        print(
            f"{stamp} CRITICAL db_fingerprint: localhost:5432 疑似旧实例——"
            f"pois={total} (<{MIN_PRODUCTION_POIS}), hours_source=amap 行数={amap}。"
            "生产库在 Docker 容器 chinatripcodes-db-1（postgis 16）；"
            "请勿在当前实例上写入，检查 Docker Desktop 是否在运行。"
        )
        return 2
    print(
        f"{stamp} db_fingerprint: ok——pois={total} (≥{MIN_PRODUCTION_POIS}), "
        f"hours_source=amap 行数={amap}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
