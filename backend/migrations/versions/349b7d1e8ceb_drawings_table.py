"""drawings table

Revision ID: 349b7d1e8ceb
Revises: bdd610292261
Create Date: 2026-06-04 18:32:46.899966

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '349b7d1e8ceb'
down_revision = 'bdd610292261'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'drawings',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('symbol', sa.String(length=10), nullable=False),
        sa.Column('interval', sa.String(length=10), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('points_json', sa.Text(), nullable=False),
        sa.Column('color', sa.String(length=20), nullable=False),
        sa.Column('width', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_drawings_symbol', 'drawings', ['symbol'], unique=False)
    op.create_index('ix_drawings_symbol_interval', 'drawings', ['symbol', 'interval'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_drawings_symbol_interval', table_name='drawings')
    op.drop_index('ix_drawings_symbol', table_name='drawings')
    op.drop_table('drawings')
