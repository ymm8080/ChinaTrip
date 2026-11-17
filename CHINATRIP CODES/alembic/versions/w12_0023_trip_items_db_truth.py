"""trip_items 数据库事实化：设备归属 + 行程号列（2026-11-13 用户拍板）。

「行程中心里的内容，行程号，行程内容，心愿单，已经安排，不要去，已经预定，
应该都是数据库的数据。当我删行程的时候，数据库里行程和行程关联的已安排就
变成无挂靠的心愿单了。」

* owner_device_id：行归属设备，看板/收口按设备读写——不再让任何会话（冒烟、
  别的浏览器）改写用户的「心愿单/已排期/不想去」。
* itinerary_ref：业务行程号（it-xxxxxxxx）原样入库；itinerary_id 是 uuid 外键
  （未保存的工作行程没有行，FK 落不了），ref 列让「挂靠/无挂靠」在库里可查。

Revision ID: w12_0023
Revises: w12_0022
Create Date: 2026-11-13

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "w12_0023"
down_revision: str | None = "w12_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "trip_items",
        sa.Column("owner_device_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "trip_items",
        sa.Column("itinerary_ref", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_trip_items_owner_device_id", "trip_items", ["owner_device_id"]
    )
    op.create_index("ix_trip_items_itinerary_ref", "trip_items", ["itinerary_ref"])


def downgrade() -> None:
    op.drop_index("ix_trip_items_itinerary_ref", table_name="trip_items")
    op.drop_index("ix_trip_items_owner_device_id", table_name="trip_items")
    op.drop_column("trip_items", "itinerary_ref")
    op.drop_column("trip_items", "owner_device_id")
