"""add the Phase G method pick to portfolio_positions

Phase G (piece 5) — the per-trade method pick: which exit method the trader
EXPLICITLY chose for a trade, the one target row that pick selected, and which
stop it was judged on.

All five columns are nullable with NO server default and NO backfill,
deliberately, and for the same reason as c7a1e9d4b820 (premium_stop_pct): NULL
is a load-bearing state, not a missing value. It means "opened before G, or
opened by a path with no human in it" — the after-scan auto-executor is exempt
from G's send gate and writes NULL here on purpose. Backfilling 'ladder' would
invent a decision nobody made, and the portfolio must render NULL as "—".

WHY THIS MIGRATION IS THE ONLY THING THAT MAKES G WORK against an existing
database: app/database.py:33-35 creates tables with Base.metadata.create_all(),
which creates missing TABLES and does NOT add columns to an existing one. On a
live PostgreSQL, adding the columns to the model alone changes nothing and every
POST /api/portfolio then fails on the missing column — AFTER the broker order
has already been placed, since every send path orders first and persists second.

down_revision is c7a1e9d4b820, which `alembic heads` confirmed on 2026-09-14 is
the single head. Four other revisions LOOK like heads if you only parse
`down_revision = '<string>'`; they are interior nodes already merged by two
merge revisions whose down_revision is a TUPLE. Chaining onto one of those would
create a genuine second head, at which point `alembic upgrade head` refuses and
— per the paragraph above — nothing else adds these columns.

Revision ID: f3d5c81b0a47
Revises: c7a1e9d4b820
Create Date: 2026-09-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f3d5c81b0a47'
down_revision = 'c7a1e9d4b820'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('portfolio_positions', sa.Column('picked_method', sa.String(), nullable=True))
    op.add_column('portfolio_positions', sa.Column('picked_row_stock_price', sa.Float(), nullable=True))
    op.add_column('portfolio_positions', sa.Column('picked_row_option_price', sa.Float(), nullable=True))
    op.add_column('portfolio_positions', sa.Column('picked_stop_basis', sa.String(), nullable=True))
    op.add_column('portfolio_positions', sa.Column('picked_at', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('portfolio_positions', 'picked_at')
    op.drop_column('portfolio_positions', 'picked_stop_basis')
    op.drop_column('portfolio_positions', 'picked_row_option_price')
    op.drop_column('portfolio_positions', 'picked_row_stock_price')
    op.drop_column('portfolio_positions', 'picked_method')
