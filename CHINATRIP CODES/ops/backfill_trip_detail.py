# -*- coding: utf-8 -*-
"""一次性回填：把已存行程的头字段 + 明细写进库（2026-11-13 用户拍板）。

「除了 TABLE CREATION.. save and deletion operation will perform creation,
change operation in table, did you create it?」

保存/删除的运行时写入已接好，但**存量行程**是功能上线前保存的——头派生列
（始/终城、旅行城市+天数、开始日期）为空、明细表没行。本脚本按 plan 回填：
  * itineraries 头派生列
  * itinerary_days / itinerary_items（snapshot_id IS NULL）
不写 change log（那不是用户点保存）。

用法：python ops/backfill_trip_detail.py [--dry-run]
"""

from __future__ import annotations

import sys

from app.db import get_session_factory
from app.models import Itinerary, ItineraryDay
from app.services.itinerary_store import ItineraryRecord
from app.services.trip_changes import rewrite_trip_detail, trip_header_fields


def main() -> None:
    dry = "--dry-run" in sys.argv
    factory = get_session_factory()
    done = 0
    with factory() as session:
        rows = session.query(Itinerary).filter(Itinerary.is_deleted.is_(False)).all()
        for row in rows:
            if not row.plan:
                continue
            try:
                record = ItineraryRecord.model_validate(row.plan)
            except Exception as exc:  # noqa: BLE001
                print("skip", row.id, "plan invalid:", exc)
                continue
            fields = trip_header_fields(record.plan)
            n_days = len(getattr(record.plan, "days", None) or [])
            n_items = sum(len(d.items or []) for d in (record.plan.days or []))
            print(
                f"{record.itinerary_id}: {fields['start_city']} → "
                f"{fields['dest_city_1']} → {fields['end_city']} · "
                f"{n_days} 天 / {n_items} 点 · 开始 {fields['travel_start_date']}"
            )
            if dry:
                continue
            for key, value in fields.items():
                setattr(row, key, value)
            rewrite_trip_detail(session, row.id, record.plan)
            done += 1
        if not dry:
            session.commit()
    print("backfilled", done, "itineraries", "(dry-run)" if dry else "")


if __name__ == "__main__":
    main()
