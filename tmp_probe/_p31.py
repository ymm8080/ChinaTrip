# -*- coding: utf-8 -*-
import io, os
p = r"D:\CHINATRIP\CHINATRIP CODES\alembic\versions\w12_0036_user_id_keying.py"
src = '''"""USER ID 归属键补齐（2026-11-14 用户拍板）。

「TRIP HEADER, TRIP ITEM, WISH LIST ARRANGMENT LIST, RESERVATION, BOOKING,
THOSE TABLES SHOULD HAVE USER ID COLUMN as key. USER ID COLUMN DETERMINED
WHEN YOU OPEN THOSE PAGE WHAT CONTENTS WILL SHOW UP.」

本系统的用户键 = 登录账号字符串（owner_account_id=用户名/邮箱，与行程头
同源）+ 浏览器设备号（owner_device_id）；users.id 外键留空（users 表不是
账号真源，账号在 SQLite accounts 域）。

* trip_items（心愿单/心愿行/已排期）：+ owner_account_id
* itinerary_items（TRIP ITEM 明细）：+ owner_device_id / owner_account_id
* action_handoffs（BOOKING/预订埋点）：+ owner_device_id / owner_account_id
* 存量回填：可 JOIN 到行程头的行从头表带归属（trip_items 按 itinerary_ref，
  itinerary_items / action_handoffs 按 itinerary_id 外键）。

Revision ID: w12_0036
Revises: w12_0035
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "w12_0036"
down_revision: str | None = "w12_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "trip_items",
        sa.Column("owner_account_id", sa.String(100), nullable=True),
    )
    op.create_index(
        "ix_trip_items_owner_account_id", "trip_items", ["owner_account_id"]
    )

    op.add_column(
        "itinerary_items",
        sa.Column("owner_device_id", sa.String(100), nullable=True),
    )
    op.add_column(
        "itinerary_items",
        sa.Column("owner_account_id", sa.String(100), nullable=True),
    )
    op.create_index(
        "ix_itinerary_items_owner_account_id",
        "itinerary_items",
        ["owner_account_id"],
    )

    op.add_column(
        "action_handoffs",
        sa.Column("owner_device_id", sa.String(100), nullable=True),
    )
    op.add_column(
        "action_handoffs",
        sa.Column("owner_account_id", sa.String(100), nullable=True),
    )
    op.create_index(
        "ix_action_handoffs_owner_account_id",
        "action_handoffs",
        ["owner_account_id"],
    )

    # 存量回填：能 JOIN 到行程头的行，归属从头表带下来（同一次保存写三表，
    # 头表 owner_* 是权威）。
    op.execute(
        """
        UPDATE trip_items t
           SET owner_account_id = i.owner_account_id
          FROM itineraries i
         WHERE t.owner_account_id IS NULL
           AND t.itinerary_ref IS NOT NULL
           AND i.plan->>'itinerary_id' = t.itinerary_ref
           AND i.owner_account_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE itinerary_items it
           SET owner_device_id = i.owner_device_id,
               owner_account_id = i.owner_account_id
          FROM itineraries i
         WHERE it.owner_account_id IS NULL
           AND it.itinerary_id = i.id
           AND (i.owner_account_id IS NOT NULL OR i.owner_device_id IS NOT NULL)
        """
    )
    op.execute(
        """
        UPDATE action_handoffs h
           SET owner_device_id = i.owner_device_id,
               owner_account_id = i.owner_account_id
          FROM itineraries i
         WHERE h.owner_account_id IS NULL
           AND h.itinerary_id = i.id
           AND (i.owner_account_id IS NOT NULL OR i.owner_device_id IS NOT NULL)
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_action_handoffs_owner_account_id", table_name="action_handoffs"
    )
    op.drop_column("action_handoffs", "owner_account_id")
    op.drop_column("action_handoffs", "owner_device_id")
    op.drop_index(
        "ix_itinerary_items_owner_account_id", table_name="itinerary_items"
    )
    op.drop_column("itinerary_items", "owner_account_id")
    op.drop_column("itinerary_items", "owner_device_id")
    op.drop_index("ix_trip_items_owner_account_id", table_name="trip_items")
    op.drop_column("trip_items", "owner_account_id")
'''
with io.open(p, "w", encoding="utf-8", newline="\n") as f:
    f.write(src)
print("wrote migration")
