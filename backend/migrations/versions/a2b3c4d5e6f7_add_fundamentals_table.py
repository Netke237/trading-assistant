"""add fundamentals table

Revision ID: a2b3c4d5e6f7
Revises: 583a54670150
Create Date: 2026-06-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a2b3c4d5e6f7'
down_revision = '583a54670150'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'fundamentals',
        sa.Column('symbol', sa.String(length=10), nullable=False),
        sa.Column('fiscal_period_end', sa.Date(), nullable=False),
        sa.Column('filed_date', sa.Date(), nullable=True),
        sa.Column('cik', sa.String(length=12), nullable=True),
        sa.Column('revenue', sa.Numeric(), nullable=True),
        sa.Column('net_income', sa.Numeric(), nullable=True),
        sa.Column('eps_diluted', sa.Numeric(), nullable=True),
        sa.Column('gross_profit', sa.Numeric(), nullable=True),
        sa.Column('operating_income', sa.Numeric(), nullable=True),
        sa.Column('op_cash_flow', sa.Numeric(), nullable=True),
        sa.Column('capex', sa.Numeric(), nullable=True),
        sa.Column('total_debt', sa.Numeric(), nullable=True),
        sa.Column('stockholders_eq', sa.Numeric(), nullable=True),
        sa.Column('current_assets', sa.Numeric(), nullable=True),
        sa.Column('current_liab', sa.Numeric(), nullable=True),
        sa.Column('shares_diluted', sa.Numeric(), nullable=True),
        sa.Column('source', sa.String(length=20), nullable=True),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('symbol', 'fiscal_period_end'),
    )


def downgrade() -> None:
    op.drop_table('fundamentals')
