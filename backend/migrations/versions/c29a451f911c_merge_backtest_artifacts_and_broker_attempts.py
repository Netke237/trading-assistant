"""merge backtest_artifacts and broker_attempts heads

Reconciles two migration branches that both forked from a93b8d24f760:

- b47d68e91a20: adds backtest_artifacts (CANDIDATE-BACKTEST-CHART, main).
- bpr001: adds broker_attempts, exposure_guards, exposure_holds and the
  portfolio prepared-order columns (BROKER-PATH-RESIDUALS).

The two branches touch disjoint tables. This migration makes no schema
changes of its own -- it is a pure merge point (see d92f6a1c8e37).

Revision ID: c29a451f911c
Revises: b47d68e91a20, bpr001
Create Date: 2026-10-15 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c29a451f911c'
down_revision = ('b47d68e91a20', 'bpr001')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
