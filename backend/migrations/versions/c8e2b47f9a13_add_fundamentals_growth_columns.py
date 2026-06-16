"""add growth-rate columns to fundamentals table

Revision ID: c8e2b47f9a13
Revises: f3d8c2a91e7b
Create Date: 2026-06-16 09:41:53.217804

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c8e2b47f9a13'
down_revision = 'f3d8c2a91e7b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('fundamentals', sa.Column('revenue_growth_yoy', sa.Float(precision=17), nullable=True))
    op.add_column('fundamentals', sa.Column('eps_growth_yoy',     sa.Float(precision=17), nullable=True))
    op.add_column('fundamentals', sa.Column('share_growth_yoy',   sa.Float(precision=17), nullable=True))


def downgrade() -> None:
    op.drop_column('fundamentals', 'share_growth_yoy')
    op.drop_column('fundamentals', 'eps_growth_yoy')
    op.drop_column('fundamentals', 'revenue_growth_yoy')
