"""merge scan_sessions and persistence_tables heads

Revision ID: e510ee3042ad
Revises: 16febdf31dd2, c157ce3cc141
Create Date: 2026-05-09 11:07:29.016690

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e510ee3042ad'
down_revision = ('16febdf31dd2', 'c157ce3cc141')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
