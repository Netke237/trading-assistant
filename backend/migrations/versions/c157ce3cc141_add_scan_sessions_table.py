"""add scan_sessions table

Revision ID: c157ce3cc141
Revises: a1b2c3d4e5f6
Create Date: 2026-05-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c157ce3cc141'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'scan_sessions',
        sa.Column('last_request_json', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('scan_sessions', 'last_request_json')
