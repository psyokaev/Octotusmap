"""rate_limit_hits: giới hạn tốc độ dùng chung giữa các worker

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("rate_limit_hits",
                    sa.Column("key", sa.String(length=300), nullable=False),
                    sa.Column("window_start", sa.DateTime(), nullable=False),
                    sa.Column("hits", sa.Integer(), nullable=False),
                    sa.PrimaryKeyConstraint("key", "window_start"))


def downgrade() -> None:
    op.drop_table("rate_limit_hits")
