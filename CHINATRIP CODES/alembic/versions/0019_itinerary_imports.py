"""行程导入流水表（2026-10-31，行程页 📥 上传 PDF/Word/Excel 生成行程单）.

全 additive：新表 itinerary_imports——文件ID（每次导入全新）为 PK，记录
源文件名/扩展名/字节数/抽取文本长度、previewed|confirmed|failed 状态、
错误与文本预览（排障用）。app 无读路径，写入失败仅告警不阻断导入主流程。

Revision ID: w12_0019
Revises: w12_0018
Create Date: 2026-10-31

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "w12_0019"
down_revision: str | None = "w12_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS itinerary_imports (
            id UUID PRIMARY KEY,
            itinerary_id UUID REFERENCES itineraries(id),
            file_name VARCHAR(255),
            ext VARCHAR(20),
            size_bytes INTEGER,
            text_chars INTEGER,
            status VARCHAR(20) NOT NULL DEFAULT 'previewed',
            error TEXT,
            text_preview TEXT,
            owner_device_id TEXT,
            owner_account_id TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            confirmed_at TIMESTAMP
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_itinerary_imports_owner_device"
        " ON itinerary_imports (owner_device_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_itinerary_imports_itinerary"
        " ON itinerary_imports (itinerary_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS itinerary_imports")
