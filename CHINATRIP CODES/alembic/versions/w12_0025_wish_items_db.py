"""心愿单数据库化：CREATED BY / ARRANGED / 删除审计 / EXCLUSION（2026-11-13 用户拍板）。

「心愿单也应该是个数据库，字段是 TRIP ID, WISH ID, WISH NAME, CREATED ON,
CREATED BY, TRIP NAME, ARRANGED, SOURCE, DELETION FLAG, DELETION DATE,
DELETION TIME, DELETED BY, EXCLUSION FLAG.」

* ARRANGED：有具体日期时刻（已排期/已订）为 true；删行程时取消（回心愿单）。
* DELETION FLAG/DATE/TIME/BY：删整趟行程时挂该 TRIP 的旧行软删留档；
  单条心愿删除同样落审计，不再物理消失。
* EXCLUSION FLAG：删行程里的站点 → 该行回心愿单并打排除标记，规划不得
  自动再排（用户明确不要这一项）。
* SOURCE：列值归一到 manual / conversation（原始来源仍全量在 payload）。
* wish_items：按用户口径命名的只读视图（trip_name 由 itineraries.title JOIN）。

Revision ID: w12_0025
Revises: w12_0024
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "w12_0025"
down_revision: str | None = "w12_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("trip_items", sa.Column("created_by", sa.String(64), nullable=True))
    op.add_column(
        "trip_items",
        sa.Column(
            "arranged", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column(
        "trip_items",
        sa.Column(
            "exclusion_flag",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "trip_items",
        sa.Column(
            "deletion_flag",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column("trip_items", sa.Column("deletion_date", sa.Date(), nullable=True))
    op.add_column("trip_items", sa.Column("deletion_time", sa.Time(), nullable=True))
    op.add_column("trip_items", sa.Column("deleted_by", sa.String(64), nullable=True))

    op.create_index("ix_trip_items_deletion_flag", "trip_items", ["deletion_flag"])
    op.create_index("ix_trip_items_arranged", "trip_items", ["arranged"])

    # 存量回填：CREATED BY 取建行设备；ARRANGED 看状态；EXCLUSION 看「不想去」
    op.execute(
        "UPDATE trip_items SET created_by = owner_device_id WHERE created_by IS NULL"
    )
    op.execute(
        "UPDATE trip_items SET arranged = true WHERE status IN ('scheduled', 'booked')"
    )
    op.execute("UPDATE trip_items SET exclusion_flag = true WHERE status = 'unwanted'")

    op.execute(
        """
        CREATE VIEW wish_items AS
        SELECT
            COALESCE(t.itinerary_ref, t.payload->>'itinerary_id') AS trip_id,
            COALESCE(t.payload->>'id', t.id::text) AS wish_id,
            t.name AS wish_name,
            t.created_at AS created_on,
            COALESCE(t.created_by, t.owner_device_id) AS created_by,
            COALESCE(
                i.title,
                array_to_string(i.cities, ' → '),
                t.payload->>'trip_name'
            )::varchar(200) AS trip_name,
            t.arranged AS arranged,
            CASE
                WHEN t.source IN ('chat', 'conversation') THEN 'conversation'
                WHEN t.source = 'manual' THEN 'manual'
                WHEN t.source = 'paste' THEN 'manual'
                ELSE t.source
            END AS source,
            t.deletion_flag AS deletion_flag,
            t.deletion_date AS deletion_date,
            t.deletion_time AS deletion_time,
            t.deleted_by AS deleted_by,
            t.exclusion_flag AS exclusion_flag
        FROM trip_items t
        LEFT JOIN itineraries i ON i.id = t.itinerary_id
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS wish_items")
    op.drop_index("ix_trip_items_arranged", table_name="trip_items")
    op.drop_index("ix_trip_items_deletion_flag", table_name="trip_items")
    op.drop_column("trip_items", "deleted_by")
    op.drop_column("trip_items", "deletion_time")
    op.drop_column("trip_items", "deletion_date")
    op.drop_column("trip_items", "deletion_flag")
    op.drop_column("trip_items", "exclusion_flag")
    op.drop_column("trip_items", "arranged")
    op.drop_column("trip_items", "created_by")
