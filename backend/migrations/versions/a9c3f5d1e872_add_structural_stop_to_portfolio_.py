"""add structural_stop to portfolio_positions

Revision ID: a9c3f5d1e872
Revises: e2a4c9f61b70
Create Date: 2026-08-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a9c3f5d1e872'
down_revision = 'e2a4c9f61b70'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('portfolio_positions', sa.Column('structural_stop', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('portfolio_positions', 'structural_stop')
