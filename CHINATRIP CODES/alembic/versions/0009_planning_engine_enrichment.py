"""规划引擎升级 0009（DESIGN planning_engine_upgrade_2026-10-24）.

A/B/C 组富化列（pois +14 / restaurants +12）+ 评论域两新表
（poi_reviews 自产评论 / poi_stats 行为热度聚合）。

铁律不变：新列全部 NULL/0 起步（存量兼容），只填空写入，时间敏感
字段只信高德/携程回源链；review_summary 由 LLM 蒸馏且 source 如实
标注。indoor/rain_ok 取值 yes/no/partial（无 CHECK，回填三层模式与
best_visit_time 同款）。

Revision ID: w12_0009
Revises: w12_0008
Create Date: 2026-10-24

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "w12_0009"
down_revision: str | None = "w12_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_POI_COLUMNS = (
    "rating_count INTEGER",
    "review_tags JSONB",
    "review_tags_source VARCHAR(20)",
    "ticket_price_min INTEGER",
    "ticket_price_max INTEGER",
    "ticket_source VARCHAR(20)",
    "district VARCHAR(50)",
    "business_area VARCHAR(50)",
    "indoor VARCHAR(10)",
    "rain_ok VARCHAR(10)",
    "name_aliases JSONB",
    "duration_source VARCHAR(20)",
    "review_summary TEXT",
    "review_summary_source VARCHAR(20)",
)

_RESTAURANT_COLUMNS = (
    "rating_count INTEGER",
    "review_tags JSONB",
    "review_tags_source VARCHAR(20)",
    "signature_dishes JSONB",
    "taste_score NUMERIC(3,1)",
    "env_score NUMERIC(3,1)",
    "service_score NUMERIC(3,1)",
    "price_level VARCHAR(10)",
    "meal_periods JSONB",
    "district VARCHAR(50)",
    "business_area VARCHAR(50)",
    "name_aliases JSONB",
)


def upgrade() -> None:
    for column_ddl in _POI_COLUMNS:
        op.execute(f"ALTER TABLE pois ADD COLUMN {column_ddl}")
    for column_ddl in _RESTAURANT_COLUMNS:
        op.execute(f"ALTER TABLE restaurants ADD COLUMN {column_ddl}")
    # 地理规划器地基：按商圈聚类分日（§6.1）走 (city, business_area) 索引
    op.execute("CREATE INDEX idx_pois_city_business ON pois (city, business_area)")
    op.execute(
        """
        CREATE TABLE poi_reviews (
            id UUID NOT NULL,
            poi_id UUID NOT NULL REFERENCES pois(id),
            user_id UUID REFERENCES users(id),
            device_id VARCHAR(64),
            rating SMALLINT,
            tags JSONB,
            text TEXT,
            visited_at TIMESTAMP,
            source VARCHAR(20),
            created_at TIMESTAMP DEFAULT NOW(),
            CONSTRAINT pk_poi_reviews PRIMARY KEY (id)
        )
        """
    )
    op.execute("CREATE INDEX idx_poi_reviews_poi ON poi_reviews (poi_id)")
    op.execute("CREATE INDEX idx_poi_reviews_user ON poi_reviews (user_id)")
    op.execute(
        """
        CREATE TABLE poi_stats (
            poi_id UUID NOT NULL REFERENCES pois(id),
            wish_count INTEGER NOT NULL DEFAULT 0,
            plan_count INTEGER NOT NULL DEFAULT 0,
            visit_count INTEGER NOT NULL DEFAULT 0,
            dislike_count INTEGER NOT NULL DEFAULT 0,
            thumbs_up INTEGER NOT NULL DEFAULT 0,
            xhs_mentions INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT NOW(),
            CONSTRAINT pk_poi_stats PRIMARY KEY (poi_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS poi_stats")
    op.execute("DROP TABLE IF EXISTS poi_reviews")
    op.execute("DROP INDEX IF EXISTS idx_pois_city_business")
    for column in (
        "name_aliases",
        "business_area",
        "district",
        "meal_periods",
        "price_level",
        "service_score",
        "env_score",
        "taste_score",
        "signature_dishes",
        "review_tags_source",
        "review_tags",
        "rating_count",
    ):
        op.execute(f"ALTER TABLE restaurants DROP COLUMN IF EXISTS {column}")
    for column in (
        "review_summary_source",
        "review_summary",
        "duration_source",
        "name_aliases",
        "rain_ok",
        "indoor",
        "business_area",
        "district",
        "ticket_source",
        "ticket_price_max",
        "ticket_price_min",
        "review_tags_source",
        "review_tags",
        "rating_count",
    ):
        op.execute(f"ALTER TABLE pois DROP COLUMN IF EXISTS {column}")
