"""add symbol notes table

Revision ID: c4a8f1d93b6e
Revises: bbb04a057515
Create Date: 2026-08-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4a8f1d93b6e'
down_revision = 'bbb04a057515'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'symbol_notes',
        sa.Column('symbol', sa.String(length=10), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('symbol'),
    )


def downgrade() -> None:
    op.drop_table('symbol_notes')
