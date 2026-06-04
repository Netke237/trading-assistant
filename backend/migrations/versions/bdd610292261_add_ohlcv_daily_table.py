"""add_ohlcv_daily_table

Revision ID: bdd610292261
Revises: d2f1a3b4c5e6
Create Date: 2026-06-04 13:06:47.464988

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'bdd610292261'
down_revision = 'd2f1a3b4c5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'ohlcv_daily',
        sa.Column('symbol', sa.String(length=10), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('open',  sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column('high',  sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column('low',   sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column('close', sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column('volume', sa.BigInteger(), nullable=False),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('symbol', 'date'),
    )


def downgrade() -> None:
    op.drop_table('ohlcv_daily')
