"""add condition_state to alert_rules

Revision ID: c1d2e3f4a5b6
Revises: a7f3e9b12c04
Create Date: 2026-07-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c1d2e3f4a5b6'
down_revision = 'a7f3e9b12c04'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'alert_rules',
        sa.Column('condition_state', sa.Text(), nullable=False, server_default='{}'),
    )


def downgrade() -> None:
    op.drop_column('alert_rules', 'condition_state')
