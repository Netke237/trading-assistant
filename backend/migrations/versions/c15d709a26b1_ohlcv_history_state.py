"""Store observed history floors and validated adjustment seams.

Revision ID: c15d709a26b1
Revises: f62a9e1b4c70
"""
from alembic import op
import sqlalchemy as sa

revision = "c15d709a26b1"
down_revision = "f62a9e1b4c70"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("ohlcv_history_state",
        sa.Column("symbol", sa.String(10), primary_key=True),
        sa.Column("floor_requested_start", sa.Date(), nullable=True),
        sa.Column("floor_date", sa.Date(), nullable=True),
        sa.Column("floor_provider", sa.String(20), nullable=True),
        sa.Column("floor_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("seam_date", sa.Date(), nullable=True),
        sa.Column("old_source", sa.String(20), nullable=True),
        sa.Column("seam_signature", sa.String(64), nullable=True))


def downgrade():
    op.drop_table("ohlcv_history_state")
