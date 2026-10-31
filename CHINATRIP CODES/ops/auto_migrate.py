"""服务启动自动迁移（2026-11-01，用户拍板「部署步骤不许靠人记」）。

由 run_h5_server.cmd / run_h5_server_tls.cmd 在 uvicorn 启动前调用：
唤醒 WSL PostgreSQL（空闲休眠）→ pg_advisory_lock 串行化 :8000/:8443
双进程并发启动 → alembic upgrade head → 放锁退出。铁律：
- PG 不可达（唤醒超时）→ 告警后 exit 0，**绝不阻塞服务启动**（app 本就
  带 PG 降级，服务起来后 keepalive 下一轮照常）；
- 已在 head → 幂等秒回，不给启动加可感延迟（~1s）；
- 锁等待上限 60s（迁移都是秒级 additive；拿不到锁说明另一进程正在迁，
  它迁完本进程也无事可做）。

被迁移的表结构变更一律 additive（IF NOT EXISTS），线上数据零风险。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # CHINATRIP CODES/

_MIGRATE_LOCK_KEY = 8633724  # 全库独立：8633722 已被 trip_items 查重锁占用
_WAKE_TOTAL_SECONDS = 45
_LOCK_WAIT_SECONDS = 60


def log(msg: str) -> None:
    print(f"[auto_migrate] {msg}", flush=True)


def wait_for_db() -> bool:
    from sqlalchemy import create_engine, text

    from app.config import get_settings

    url = get_settings().database_url
    deadline = time.time() + _WAKE_TOTAL_SECONDS
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            eng = create_engine(url, connect_args={"connect_timeout": 3})
            with eng.connect() as conn:
                conn.execute(text("select 1"))
            eng.dispose()
            log(f"db reachable after {attempt} probe(s)")
            return True
        except Exception:
            time.sleep(3)
    log(f"WARN: db unreachable after {attempt} probes (~{_WAKE_TOTAL_SECONDS}s),"
        " skip migration — service starts anyway (app has PG degrade)")
    return False


def main() -> int:
    os.chdir(ROOT)  # alembic.ini / script_location 均按此目录解析
    sys.path.insert(0, str(ROOT))
    if not wait_for_db():
        return 0
    from sqlalchemy import create_engine, text

    from alembic import command as alembic_command
    from alembic.config import Config

    from app.config import get_settings

    lock_eng = create_engine(get_settings().database_url,
                             connect_args={"connect_timeout": 3})
    conn = lock_eng.connect()
    got = False
    deadline = time.time() + _LOCK_WAIT_SECONDS
    while time.time() < deadline:
        if conn.execute(text(f"select pg_try_advisory_lock({_MIGRATE_LOCK_KEY})")).scalar():
            got = True
            break
        time.sleep(2)
    if not got:
        log("WARN: 另一进程迁移超 60s 未放锁，跳过（它迁完即等价）")
        conn.close()
        lock_eng.dispose()
        return 0
    try:
        cfg = Config(str(ROOT / "alembic.ini"))
        alembic_command.upgrade(cfg, "head")
        log("alembic upgrade head: done (or already at head)")
    except Exception as exc:
        # 迁移失败也放服务启动：失败细节在日志里，服务照旧跑旧表结构
        # （additive 迁移不跑 = 新表缺失，对应功能报错但存量功能无损）。
        log(f"ERROR: alembic upgrade failed: {exc}")
    finally:
        conn.execute(text(f"select pg_advisory_unlock({_MIGRATE_LOCK_KEY})"))
        conn.close()
        lock_eng.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
