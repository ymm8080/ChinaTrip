"""一次性修复（2026-10-31 看水利工程案）：trip_items.itinerary_id 列回填.

根因：item_to_row_values 此前按严格 UUID 解析行程 id，业务短格式
（it-<8hex>）一律解析为 None → 心愿行 payload 里绑得好（已排期、note 已
写），PG 列里却是 NULL；行程中心按行程过滤 / 任何列级读者全部丢行。
item_to_row_values 改 loose 代理（与 itineraries 行主键同源）后，本脚本把
库内全部 payload 重新写穿一遍：幂等 upsert，FK 目标不存在时 IntegrityError
回退清列（payload 原值不受影响）。

前置：PG 可达 + 代码含 loose 修复。用法（任意 cwd）：

    .venv\\Scripts\\python.exe ops\\repair_trip_item_itin_columns.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.db import get_session_factory  # noqa: E402
from app.services.pg_state import PgTripItemService  # noqa: E402

_CHECK = (
    "SELECT payload->>'name', payload->>'itinerary_id', itinerary_id::text"
    " FROM trip_items"
    " WHERE payload->>'itinerary_id' IS NOT NULL ORDER BY payload->>'name'"
)


def _columns(factory) -> list:
    with factory() as session:
        return session.execute(text(_CHECK)).all()


def main() -> int:
    factory = get_session_factory()
    svc = PgTripItemService(factory)
    if not svc._pg_ok:
        print("PG 不可达（boot 熔断），未做任何修改")
        return 1

    print("修复前（name | payload 绑定 | itinerary_id 列）:")
    for name, biz, col in _columns(factory):
        print(f"  {name} | {biz} | {col}")

    payloads = list(svc._items.values())
    for payload in payloads:
        svc.import_item(dict(payload))  # 幂等写穿：列按 loose 代理重算

    print(f"已全量重写穿 {len(payloads)} 条。修复后:")
    broken = 0
    for name, biz, col in _columns(factory):
        print(f"  {name} | {biz} | {col}")
        if col is None:
            broken += 1
    if broken:
        print(f"{broken} 条列仍为 NULL（FK 目标不存在被回退清列，属预期）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
