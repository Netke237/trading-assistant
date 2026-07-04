"""add entry_stock_price to portfolio_positions

Revision ID: f14c8c7e35e8
Revises: c8e2b47f9a13
Create Date: 2026-07-04 16:53:29.914069

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f14c8c7e35e8'
down_revision = 'c8e2b47f9a13'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('portfolio_positions', sa.Column('entry_stock_price', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('portfolio_positions', 'entry_stock_price')
