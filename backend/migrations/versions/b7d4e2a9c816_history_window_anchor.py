"""Add the nightly window anchor to ohlcv_history_state (HISTORY-INCREMENTAL-NIGHTLY B0).

Revision ID: b7d4e2a9c816
Revises: e5c1a7d3b902

down_revision is e5c1a7d3b902, the single head on 2026-10-21. No data change:
NULL means "no anchor" and routes the symbol to today's full single-provider path.
"""
from alembic import op
import sqlalchemy as sa

revision = "b7d4e2a9c816"
down_revision = "e5c1a7d3b902"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ohlcv_history_state",
                  sa.Column("window_verified_through", sa.Date(), nullable=True))
    op.add_column("ohlcv_history_state",
                  sa.Column("window_verified_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table("ohlcv_history_state") as batch_op:
        batch_op.drop_column("window_verified_at")
        batch_op.drop_column("window_verified_through")
