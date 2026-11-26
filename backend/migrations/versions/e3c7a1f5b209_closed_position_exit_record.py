"""Add the exit record to closed_positions (PORTFOLIO-EXIT-RECORD, #664).

Revision ID: e3c7a1f5b209
Revises: d6a2f9c4e017

down_revision is d6a2f9c4e017, the single head on 2026-11-26. Five nullable
columns with no server default: rows closed before this change read NULL
("not recorded") and are never back-filled. Downgrade drops them inside a
batch_alter_table (SQLite needs batch mode to drop a column).
"""
from alembic import op
import sqlalchemy as sa

revision = "e3c7a1f5b209"
down_revision = "d6a2f9c4e017"
branch_labels = None
depends_on = None

_FLOAT_COLUMNS = (
    "stop_at_close",
    "structural_stop_at_close",
    "premium_stop_pct_at_close",
    "premium_stop_price_at_close",
)


def upgrade():
    op.add_column("closed_positions", sa.Column("exit_reason", sa.String(20), nullable=True))
    for name in _FLOAT_COLUMNS:
        op.add_column("closed_positions", sa.Column(name, sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table("closed_positions") as batch:
        for name in reversed(_FLOAT_COLUMNS):
            batch.drop_column(name)
        batch.drop_column("exit_reason")
