"""心愿单补规划字段（2026-11-13 用户问「按行程规划细节还缺哪些列」）。

规划器每个点位（VisitItem）实际用到的决策输入，落在心愿行上：

* kind：sight/food/hotel/transfer——决定进景点卡/餐卡/酒店卡哪条装配线；
* duration_minutes：日容量与可行性（选层/让位/回填都按它算分钟）；
* must_visit / pinned：铁律 19 —— 必去与用户钉住不得被求解器挪走；
* tier / site_rank：名录档与名录秩（UNESCO/5A/curated…，族日择日与
  让位弹座的排序依据）；
* latitude / longitude：归簇择日、动线腿距（不必每次回库反查）；
* planned_date / start_time / end_time：ARRANGED 的「具体日期时刻」本体
  （day 只是天序，日期 = 出发日 + day-1）；
* arranged_at：什么时候被排上的（审计）；
* rain_ok：雨天硬闸的室内/露天属性（yes/no/partial）；
* raw_command：用户原话（手工/对话），审计与复现用。

Revision ID: w12_0029
Revises: w12_0028
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "w12_0029"
down_revision: str | None = "w12_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("trip_items", sa.Column("kind", sa.String(20), nullable=True))
    op.add_column("trip_items", sa.Column("duration_minutes", sa.Integer(), nullable=True))
    op.add_column(
        "trip_items",
        sa.Column(
            "must_visit", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column(
        "trip_items",
        sa.Column(
            "pinned", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column("trip_items", sa.Column("tier", sa.SmallInteger(), nullable=True))
    op.add_column("trip_items", sa.Column("site_rank", sa.SmallInteger(), nullable=True))
    op.add_column(
        "trip_items", sa.Column("latitude", sa.Float(), nullable=True)
    )
    op.add_column(
        "trip_items", sa.Column("longitude", sa.Float(), nullable=True)
    )
    op.add_column("trip_items", sa.Column("planned_date", sa.Date(), nullable=True))
    op.add_column("trip_items", sa.Column("start_time", sa.Time(), nullable=True))
    op.add_column("trip_items", sa.Column("end_time", sa.Time(), nullable=True))
    op.add_column(
        "trip_items", sa.Column("raw_command", sa.String(1000), nullable=True)
    )
    op.add_column(
        "trip_items", sa.Column("arranged_at", sa.TIMESTAMP(), nullable=True)
    )

    # 存量回填：kind 按 source/状态无从推断，留空；must/pinned 默认 false。
    # 已排期行补 arranged_at = updated_at（审计近似值）。
    op.execute(
        "UPDATE trip_items SET arranged_at = updated_at"
        " WHERE arranged = true AND arranged_at IS NULL"
    )

    # 视图加列（只追加在末尾，CREATE OR REPLACE 允许）
    op.execute(
        """
        CREATE OR REPLACE VIEW wish_items AS
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


def downgrade() -> None:
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
            t.exclusion_flag AS exclusion_flag
        FROM trip_items t
        LEFT JOIN itineraries i ON i.id = t.itinerary_id
        """
    )
    for column in (
        "arranged_at",
        "raw_command",
        "end_time",
        "start_time",
        "planned_date",
        "longitude",
        "latitude",
        "site_rank",
        "tier",
        "pinned",
        "must_visit",
        "duration_minutes",
        "kind",
    ):
        op.drop_column("trip_items", column)
