# -*- coding: utf-8 -*-
import io

# 1) models.py: drop owner_device_id from ItineraryItem & ActionHandoff (keep owner_account_id)
p = r"D:\CHINATRIP\CHINATRIP CODES\app\models.py"
t = io.open(p, encoding="utf-8", newline="").read()

def sub(old, new, n=1):
    global t
    c = t.count(old)
    assert c == n, (c, old[:90])
    t = t.replace(old, new)

sub('''    # 2026-11-14（用户拍板「TRIP HEADER/ITEM/心愿单/预订都要 USER ID 列，
    # 打开页面按 USER ID 出内容」）：明细行冗余归属键——不 JOIN 头表也能按
    # 用户直查；值由保存路径从头表带下来。
    owner_device_id: Mapped[str | None] = mapped_column(String(100))
    owner_account_id: Mapped[str | None] = mapped_column(String(100), index=True)
''', '''    # 2026-11-14（用户拍板「TRIP ITEM 也要 USER ID 列，打开页面按 USER ID
    # 出内容；不需要设备列」）：明细行冗余用户键——不 JOIN 头表也能按用户
    # 直查；值由保存路径从头表带下来。
    owner_account_id: Mapped[str | None] = mapped_column(String(100), index=True)
''')
sub('''    # 2026-11-14（用户拍板「预订/代订埋点也要 USER ID 列」）：归属键用与本
    # 系统一致的字符串账号（owner_account_id=登录名/邮箱）+ 设备号；
    # users.id 外键留空（users 表非账号真源）。
    owner_device_id: Mapped[str | None] = mapped_column(String(100), index=True)
    owner_account_id: Mapped[str | None] = mapped_column(String(100), index=True)
''', '''    # 2026-11-14（用户拍板「预订/代订埋点也要 USER ID 列，不需要设备列」）：
    # 归属键 = 登录账号字符串（owner_account_id=用户名/邮箱，与行程头同源）；
    # users.id 外键留空（users 表非账号真源）。
    owner_account_id: Mapped[str | None] = mapped_column(String(100), index=True)
''')
io.open(p, "w", encoding="utf-8", newline="").write(t)
print("models ok")

# 2) migration w12_0036 rewrite: account id only
p2 = r"D:\CHINATRIP\CHINATRIP CODES\alembic\versions\w12_0036_user_id_keying.py"
src = '''"""USER ID 归属键补齐（2026-11-14 用户拍板）。

「TRIP HEADER, TRIP ITEM, WISH LIST ARRANGMENT LIST, RESERVATION, BOOKING,
THOSE TABLES SHOULD HAVE USER ID COLUMN as key. USER ID COLUMN DETERMINED
WHEN YOU OPEN THOSE PAGE WHAT CONTENTS WILL SHOW UP.」
「WE DO NOT NEED OWNER DEVICE ID COLUMN.」

用户键 = 登录账号字符串（owner_account_id=用户名/邮箱，与行程头同源）；
不加设备列（users.id 外键留空，users 表不是账号真源）。

* trip_items（心愿单/心愿行/已排期）：+ owner_account_id
* itinerary_items（TRIP ITEM 明细）：+ owner_account_id
* action_handoffs（BOOKING/预订埋点）：+ owner_account_id
* 存量回填：能 JOIN 到行程头的行从头表带 owner_account_id（trip_items 按
  itinerary_ref，itinerary_items / action_handoffs 按 itinerary_id 外键）。

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
        sa.Column("owner_account_id", sa.String(100), nullable=True),
    )
    op.create_index(
        "ix_itinerary_items_owner_account_id",
        "itinerary_items",
        ["owner_account_id"],
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

    # 存量回填：能 JOIN 到行程头的行，USER ID 从头表带下来（同一次保存写
    # 三表，头表 owner_account_id 是权威）。
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
           SET owner_account_id = i.owner_account_id
          FROM itineraries i
         WHERE it.owner_account_id IS NULL
           AND it.itinerary_id = i.id
           AND i.owner_account_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE action_handoffs h
           SET owner_account_id = i.owner_account_id
          FROM itineraries i
         WHERE h.owner_account_id IS NULL
           AND h.itinerary_id = i.id
           AND i.owner_account_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_action_handoffs_owner_account_id", table_name="action_handoffs"
    )
    op.drop_column("action_handoffs", "owner_account_id")
    op.drop_index(
        "ix_itinerary_items_owner_account_id", table_name="itinerary_items"
    )
    op.drop_column("itinerary_items", "owner_account_id")
    op.drop_index("ix_trip_items_owner_account_id", table_name="trip_items")
    op.drop_column("trip_items", "owner_account_id")
'''
io.open(p2, "w", encoding="utf-8", newline="\n").write(src)
print("migration rewritten")
