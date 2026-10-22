"""add hold_max_days to portfolio_positions

STOCKS-HORIZON-T1 H6 -- a stock position records the scan's hold (calendar
days); alert_generator raises TIME_STOP once the position has been held that
long. Nullable, no server default, no backfill: NULL means "no hold" (options
rows, rows opened before H6, paths with no scan) and never fires.

Needed against an existing database because app/database.py's create_all()
creates missing tables only, never missing columns.

down_revision is c15d709a26b1 (STOCKS-HORIZON-HISTORY), the single head on main
after HISTORY merged (2026-10-09); first written against f62a9e1b4c70.

Revision ID: e7b2d4a91c58
Revises: c15d709a26b1
Create Date: 2026-10-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e7b2d4a91c58'
down_revision = 'c15d709a26b1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('portfolio_positions', sa.Column('hold_max_days', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('portfolio_positions', 'hold_max_days')
