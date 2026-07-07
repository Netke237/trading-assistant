"""add alert_state to portfolio_positions

Revision ID: b4e91a2f7c33
Revises: c1d2e3f4a5b6
Create Date: 2026-07-04 00:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b4e91a2f7c33'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'portfolio_positions',
        sa.Column('alert_state', sa.JSON(), nullable=True, server_default='{}'),
    )


def downgrade() -> None:
    op.drop_column('portfolio_positions', 'alert_state')
