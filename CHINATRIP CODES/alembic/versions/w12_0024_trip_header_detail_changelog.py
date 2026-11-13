"""trip 头/明细/变更日志（2026-11-13 用户拍板）。

「trip 内容也需要成数据库，需要 trip HEADER WHICH CONTAINS CREATION DATE,
CREATOR, DELETION FLAG, TRIP ID, TRIP NAME ETC. LAST CHANGE DATE, LAST
CHANGE TIME.」
「TRIP 还需要有详情数据库，WHICH STORED EACH DATE AND TIME AND SITES,
ALTERNATIVE INFORMATION. WE ALSO NEED A CHANGE LOG DATASET WHICH STORED
USER, USER NAME, CHANGES AFTER CLICK SAVE BUTTON.」

* itineraries（头）：is_deleted/deleted_at（软删）、creator_name、last_changed_at；
  created_at / title / owner_device_id / owner_account_id 既有。
* itinerary_items（明细）：补 name/city/category/address/alternatives——每天每时
 段落的点位与备选（alternatives）落库，不再只活在 plan JSON。
* itinerary_change_log（变更日志）：每次点「💾 保存行程」写一行——设备、账号、
  变更人、变更摘要、逐条 diff（JSONB）、同步版本。

Revision ID: w12_0024
Revises: w12_0023
Create Date: 2026-11-13
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "w12_0024"
down_revision: str | None = "w12_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "itineraries",
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "itineraries",
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "itineraries", sa.Column("creator_name", sa.String(100), nullable=True)
    )
    op.add_column(
        "itineraries",
        sa.Column("last_changed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )

    op.add_column("itinerary_items", sa.Column("name", sa.String(200), nullable=True))
    op.add_column("itinerary_items", sa.Column("city", sa.String(50), nullable=True))
    op.add_column(
        "itinerary_items", sa.Column("category", sa.String(40), nullable=True)
    )
    op.add_column(
        "itinerary_items", sa.Column("address", sa.String(200), nullable=True)
    )
    op.add_column(
        "itinerary_items",
        sa.Column("alternatives", JSONB(none_as_null=True), nullable=True),
    )

    op.create_table(
        "itinerary_change_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "itinerary_id",
            UUID(as_uuid=True),
            sa.ForeignKey("itineraries.id"),
            nullable=True,
        ),
        sa.Column("itinerary_ref", sa.String(64), nullable=True),
        sa.Column("owner_device_id", sa.String(100), nullable=True),
        sa.Column("owner_account_id", sa.String(100), nullable=True),
        sa.Column("actor_name", sa.String(100), nullable=True),
        sa.Column(
            "changed_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("sync_version", sa.Integer(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("changes", JSONB(none_as_null=True), nullable=True),
        sa.Column("snapshot_id", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_itinerary_change_log_itinerary_id",
        "itinerary_change_log",
        ["itinerary_id", "changed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_itinerary_change_log_itinerary_id", table_name="itinerary_change_log"
    )
    op.drop_table("itinerary_change_log")
    for col in ("alternatives", "address", "category", "city", "name"):
        op.drop_column("itinerary_items", col)
    for col in ("last_changed_at", "creator_name", "deleted_at", "is_deleted"):
        op.drop_column("itineraries", col)
