"""行程/快照/心愿单 H5 状态落 PG（B 期：行程保存即入库，2026-10-25）.

H5 行程域此前只写 SQLite 状态库（data/h5_state.db），PG 三表（itineraries/
itinerary_snapshots/trip_items）自 0001 建表以来 0 行——天气巡检 trip_cities
查 PG 永远为空（2026-10-25 排障定案：行程保存过程必须落 PG）。本迁移全
additive：itineraries 加 plan JSONB（ItineraryRecord 整体文档）+ owner/share
列；snapshots 加 plan；trip_items 加 payload。数据由 ops/migrate_h5_state_to_pg.py
搬移，SQLite 文件原样保留为备份。

Revision ID: w12_0015
Revises: w12_0014
Create Date: 2026-10-25

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "w12_0015"
down_revision: str | None = "w12_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE itineraries
            ADD COLUMN IF NOT EXISTS plan JSONB,
            ADD COLUMN IF NOT EXISTS owner_device_id TEXT,
            ADD COLUMN IF NOT EXISTS owner_account_id TEXT,
            ADD COLUMN IF NOT EXISTS share_enabled BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS share_token TEXT
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_itineraries_owner_device"
        " ON itineraries (owner_device_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_itineraries_owner_account"
        " ON itineraries (owner_account_id)"
    )
    # 分享令牌只在开启分享时存在——部分唯一索引，避免空值互斥
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_itineraries_share_token"
        " ON itineraries (share_token) WHERE share_token IS NOT NULL"
    )
    op.execute("ALTER TABLE itinerary_snapshots ADD COLUMN IF NOT EXISTS plan JSONB")
    op.execute("ALTER TABLE trip_items ADD COLUMN IF NOT EXISTS payload JSONB")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_itineraries_share_token")
    op.execute("DROP INDEX IF EXISTS idx_itineraries_owner_account")
    op.execute("DROP INDEX IF EXISTS idx_itineraries_owner_device")
    op.execute(
        """
        ALTER TABLE itineraries
            DROP COLUMN IF EXISTS share_token,
            DROP COLUMN IF EXISTS share_enabled,
            DROP COLUMN IF EXISTS owner_account_id,
            DROP COLUMN IF EXISTS owner_device_id,
            DROP COLUMN IF EXISTS plan
        """
    )
    op.execute("ALTER TABLE itinerary_snapshots DROP COLUMN IF EXISTS plan")
    op.execute("ALTER TABLE trip_items DROP COLUMN IF EXISTS payload")
