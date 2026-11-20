"""cameras: theo dõi ảnh camera giao thông (lần kiểm tra gần nhất, số lần lỗi liên tiếp)

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cameras", sa.Column("snapshot_checked_at", sa.DateTime(), nullable=True))
    op.add_column("cameras", sa.Column("snapshot_fail_count", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("cameras", "snapshot_fail_count")
    op.drop_column("cameras", "snapshot_checked_at")
