"""v2.5 POI 底库 (DESIGN §4.2): pois 扩列 + restaurants 独立表.

铁律——外部源仅写骨架（名称/坐标/类别），时间敏感字段
（hours/price/duration）只信高德/携程回源链。餐厅分表（用户拍板
2026-10-23），骨架列与 pois 同构。

Revision ID: w12_0006
Revises: w12_0005
Create Date: 2026-10-23

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "w12_0006"
down_revision: str | None = "w12_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_POI_COLUMNS = (
    "phone VARCHAR(50)",
    "website VARCHAR(300)",
    "rating NUMERIC(3,1)",
    "rating_source VARCHAR(20)",
    "tags JSONB",
    "tags_source VARCHAR(20)",
    "intro TEXT",
    "intro_source VARCHAR(20)",
    "photos JSONB",
    "photos_source VARCHAR(20)",
    "best_visit_time VARCHAR(10) NOT NULL DEFAULT 'any'",
    "best_visit_time_source VARCHAR(20)",
    "suggested_duration_min INTEGER",
    "origin VARCHAR(20)",
)


def upgrade() -> None:
    for column_ddl in _POI_COLUMNS:
        op.execute(f"ALTER TABLE pois ADD COLUMN {column_ddl}")
    op.execute(
        "ALTER TABLE pois ADD CONSTRAINT ck_pois_best_visit_time "
        "CHECK (best_visit_time IN "
        "('sunrise','morning','afternoon','evening','sunset','any'))"
    )
    op.execute(
        """
        CREATE TABLE restaurants (
            id UUID NOT NULL,
            source VARCHAR(20) NOT NULL,
            source_poi_id VARCHAR(100) NOT NULL,
            city VARCHAR(50) NOT NULL,
            name_zh VARCHAR(200),
            name_en VARCHAR(200),
            cuisine VARCHAR(50),
            status VARCHAR(20) DEFAULT 'active',
            location geography(POINT, 4326),
            wgs84_location geography(POINT, 4326),
            address VARCHAR(200),
            opening_hours VARCHAR(500),
            hours_source VARCHAR(20),
            hours_updated_at TIMESTAMP,
            phone VARCHAR(50),
            website VARCHAR(300),
            avg_cost NUMERIC(10,2),
            rating NUMERIC(3,1),
            rating_source VARCHAR(20),
            tags JSONB,
            tags_source VARCHAR(20),
            intro TEXT,
            intro_source VARCHAR(20),
            photos JSONB,
            photos_source VARCHAR(20),
            origin VARCHAR(20),
            updated_at TIMESTAMP DEFAULT NOW(),
            CONSTRAINT pk_restaurants PRIMARY KEY (id),
            CONSTRAINT uq_restaurants_source UNIQUE (source, source_poi_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_restaurants_location ON restaurants USING GIST (location)"
    )
    op.execute("CREATE INDEX idx_restaurants_city ON restaurants (city)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_restaurants_city")
    op.execute("DROP INDEX IF EXISTS idx_restaurants_location")
    op.execute("DROP TABLE restaurants")
    op.execute("ALTER TABLE pois DROP CONSTRAINT ck_pois_best_visit_time")
    for column_ddl in reversed(_POI_COLUMNS):
        column_name = column_ddl.split()[0]
        op.execute(f"ALTER TABLE pois DROP COLUMN {column_name}")
