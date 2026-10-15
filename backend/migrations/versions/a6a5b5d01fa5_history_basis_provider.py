"""Record a single-provider history basis per symbol.

Revision ID: a6a5b5d01fa5
Revises: a93b8d24f760
"""
from alembic import op
import sqlalchemy as sa

revision = "a6a5b5d01fa5"
down_revision = "a93b8d24f760"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ohlcv_history_state",
                  sa.Column("basis_provider", sa.String(20), nullable=True))
    op.add_column("ohlcv_history_state",
                  sa.Column("basis_rebuilt_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table("ohlcv_history_state") as batch_op:
        batch_op.drop_column("basis_rebuilt_at")
        batch_op.drop_column("basis_provider")
