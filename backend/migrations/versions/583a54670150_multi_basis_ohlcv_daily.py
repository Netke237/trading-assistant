"""multi_basis_ohlcv_daily

Revision ID: 583a54670150
Revises: 3a503885d759
Create Date: 2026-06-11 16:15:13.338388

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '583a54670150'
down_revision = '3a503885d759'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('ohlcv_daily', sa.Column('adj_factor',   sa.Numeric(precision=12, scale=8), nullable=True))
    op.add_column('ohlcv_daily', sa.Column('split_factor', sa.Numeric(precision=12, scale=8), nullable=True))
    op.add_column('ohlcv_daily', sa.Column('div_cash',     sa.Numeric(precision=12, scale=4), nullable=True))
    op.add_column('ohlcv_daily', sa.Column('source',       sa.String(length=20),              nullable=True))
    # Existing rows store adjClose in close — set adj_factor=1.0 so the
    # invariant raw_close × adj_factor = fully_adjusted_close holds.
    op.execute("UPDATE ohlcv_daily SET adj_factor = 1.0, split_factor = 1.0, div_cash = 0.0, source = 'tiingo_legacy' WHERE adj_factor IS NULL")


def downgrade() -> None:
    op.drop_column('ohlcv_daily', 'source')
    op.drop_column('ohlcv_daily', 'div_cash')
    op.drop_column('ohlcv_daily', 'split_factor')
    op.drop_column('ohlcv_daily', 'adj_factor')
