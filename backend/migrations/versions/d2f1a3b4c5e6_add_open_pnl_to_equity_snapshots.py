"""add open_pnl to equity_snapshots

Revision ID: d2f1a3b4c5e6
Revises: ad10598425a1
Create Date: 2026-06-01 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd2f1a3b4c5e6'
down_revision = 'ad10598425a1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'equity_snapshots',
        sa.Column('open_pnl', sa.Float(), nullable=False, server_default='0.0'),
    )


def downgrade() -> None:
    op.drop_column('equity_snapshots', 'open_pnl')
