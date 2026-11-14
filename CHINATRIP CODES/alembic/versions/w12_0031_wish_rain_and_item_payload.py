"""心愿 + 行程明细收口（2026-11-13 用户拍板）。

心愿表：
* rain_ok 加回（来自 POIS 的室内/露天属性；天气本身每日刷新不入库）；
* arranged_at 取消——「排定时间」= trip 表创建时间 + change 表变更时间。

行程明细表（VisitItem/酒店/交通/餐卡都要在详情库里）：
* payload：整条 item 的 model_dump（酒店卡/餐卡/景点卡的扩展字段全量留档）；
* pinned / must_visit / tier / site_rank / note / transport_mode / seq：
  规划语义列，明细行可独立查询。

Revision ID: w12_0031
Revises: w12_0030
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "w12_0031"
down_revision: str | None = "w12_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- 心愿表 ---------------------------------------------------------
    # 视图先拆（wish_items 依赖 arranged_at 列，直接 DROP COLUMN 会被挡住）
    op.execute("DROP VIEW IF EXISTS wish_items")
    op.add_column("trip_items", sa.Column("rain_ok", sa.String(10), nullable=True))
    op.drop_column("trip_items", "arranged_at")

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
                WHEN t.source IN ('manual', 'paste') THEN 'manual'
                ELSE t.source
            END AS source,
            t.deletion_flag AS deletion_flag,
            t.deletion_date AS deletion_date,
            t.deletion_time AS deletion_time,
            t.deleted_by AS deleted_by,
            t.exclusion_flag AS exclusion_flag,
            t.kind AS kind,
            t.duration_minutes AS duration_minutes,
            t.must_visit AS must_visit,
            t.pinned AS pinned,
            t.tier AS tier,
            t.site_rank AS site_rank,
            t.latitude AS latitude,
            t.longitude AS longitude,
            t.rain_ok AS rain_ok,
            t.planned_date AS planned_date,
            t.start_time AS start_time,
            t.end_time AS end_time,
            t.raw_command AS raw_command
        FROM trip_items t
        LEFT JOIN itineraries i ON i.id = t.itinerary_id
        """
    )

    # --- 行程明细表 -----------------------------------------------------
    op.add_column(
        "itinerary_items", sa.Column("payload", JSONB(none_as_null=True), nullable=True)
    )
    op.add_column(
        "itinerary_items",
        sa.Column(
            "pinned", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column(
        "itinerary_items",
        sa.Column(
            "must_visit", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column(
        "itinerary_items", sa.Column("tier", sa.SmallInteger(), nullable=True)
    )
    op.add_column(
        "itinerary_items", sa.Column("site_rank", sa.SmallInteger(), nullable=True)
    )
    op.add_column("itinerary_items", sa.Column("note", sa.Text(), nullable=True))
    op.add_column("itinerary_items", sa.Column("seq", sa.Integer(), nullable=True))
    op.create_index(
        "ix_itinerary_items_item_ref", "itinerary_items", ["itinerary_id", "item_ref"]
    )


def downgrade() -> None:
    op.drop_index("ix_itinerary_items_item_ref", table_name="itinerary_items")
    for column in (
        "seq",
        "note",
        "site_rank",
        "tier",
        "must_visit",
        "pinned",
        "payload",
    ):
        op.drop_column("itinerary_items", column)

    op.drop_column("trip_items", "rain_ok")
    op.add_column("trip_items", sa.Column("arranged_at", sa.TIMESTAMP(), nullable=True))
    op.execute("DROP VIEW IF EXISTS wish_items")
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
                WHEN t.source IN ('manual', 'paste') THEN 'manual'
                ELSE t.source
            END AS source,
            t.deletion_flag AS deletion_flag,
            t.deletion_date AS deletion_date,
            t.deletion_time AS deletion_time,
            t.deleted_by AS deleted_by,
            t.exclusion_flag AS exclusion_flag,
            t.kind AS kind,
            t.duration_minutes AS duration_minutes,
            t.must_visit AS must_visit,
            t.pinned AS pinned,
            t.tier AS tier,
            t.site_rank AS site_rank,
            t.latitude AS latitude,
            t.longitude AS longitude,
            t.planned_date AS planned_date,
            t.start_time AS start_time,
            t.end_time AS end_time,
            t.raw_command AS raw_command,
            t.arranged_at AS arranged_at
        FROM trip_items t
        LEFT JOIN itineraries i ON i.id = t.itinerary_id
        """
    )
