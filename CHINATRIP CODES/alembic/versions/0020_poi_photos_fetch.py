"""照片回源元数据列（2026-11-11，DESIGN poi_photos_functional_design §3-F2/F4）.

pois / restaurants 各加两列（同构）：
- photos_fetched_at TIMESTAMP NULL：最近一次回源尝试戳。24h 点击冷却键——
  语义上"尝试"即落戳（拉空也落），否则空图行连点会无限烧图商配额；
  照片本体 photos/photos_source 仍严守只填空铁律（非空才写）。
- photos_fetch_fail INT NOT NULL DEFAULT 0：F4 死图上报计数（前端
  onerror fire-and-forget POST /api/pois/photos/report-dead），>=3 由
  日/周刷新 job 触发整组重拉（刷新语义另案拍板，本迁移只落列）。

纯 additive，无数据回填（历史行两列留 NULL/0，无图行本就未尝试回源）。

Revision ID: w12_0020
Revises: w12_0019
Create Date: 2026-11-11

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "w12_0020"
down_revision: str | None = "w12_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("pois", "restaurants")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS photos_fetched_at TIMESTAMP"
        )
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS photos_fetch_fail"
            " INTEGER NOT NULL DEFAULT 0"
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS photos_fetch_fail")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS photos_fetched_at")
