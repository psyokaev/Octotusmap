"""satellite_rainfall_daily: mưa vệ tinh GPM IMERG theo ngày, theo quận

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("satellite_rainfall_daily",
                    sa.Column("id", sa.Integer(), primary_key=True),
                    sa.Column("area_id", sa.Integer(), sa.ForeignKey("administrative_areas.id"), nullable=False),
                    sa.Column("day", sa.Date(), nullable=False),
                    sa.Column("rain_mm", sa.Float(), nullable=False),
                    sa.Column("product", sa.String(length=30), nullable=False),
                    sa.Column("fetched_at", sa.DateTime(), nullable=False),
                    sa.UniqueConstraint("area_id", "day", "product", name="uq_satrain_area_day"))
    op.create_index("ix_satellite_rainfall_daily_area_id", "satellite_rainfall_daily", ["area_id"])
    op.create_index("ix_satellite_rainfall_daily_day", "satellite_rainfall_daily", ["day"])


def downgrade() -> None:
    op.drop_table("satellite_rainfall_daily")
