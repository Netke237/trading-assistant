"""add premium_stop_pct to portfolio_positions

Piece 4 — the per-position premium stop.

Nullable with NO server default and NO backfill, deliberately. NULL means
"inherit the global" (risk_rules.yaml -> reward_risk.premium_stop_pct) and is
a load-bearing state, not a missing value: backfilling every existing row with
0.60 would freeze those positions at today's global and stop them responding
when it changes, which is exactly the behaviour this piece removes. Existing
open positions stay NULL and keep inheriting.

Revision ID: c7a1e9d4b820
Revises: 2bf3bf834b29
Create Date: 2026-09-03 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c7a1e9d4b820'
down_revision = '2bf3bf834b29'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'portfolio_positions',
        sa.Column('premium_stop_pct', sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('portfolio_positions', 'premium_stop_pct')
