"""merge alert_state and audit-schema-drift heads

Reconciles two migration branches that both forked from a7f3e9b12c04
without either accounting for the other:

- b3f7a1c9d4e2 (2026-07-15): fixes audit_events/portfolio_positions type
  drift. Already applied to the live database.
- b4e91a2f7c33 <- c1d2e3f4a5b6 (2026-07-04): adds alert_rules.condition_state
  and portfolio_positions.alert_state. Never applied to the live database,
  because the db's alembic_version pointer was on the other branch and
  `alembic upgrade head` had two heads to choose from with no merge point
  connecting them.

This migration makes no schema changes of its own -- it is a pure merge
point. Running `alembic upgrade head` after this migration exists will
apply whichever of the two branches' migrations the target database is
missing (for the live db: c1d2e3f4a5b6 and b4e91a2f7c33) to reach this
merge revision.

Revision ID: d92f6a1c8e37
Revises: b3f7a1c9d4e2, b4e91a2f7c33
Create Date: 2026-07-17 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd92f6a1c8e37'
down_revision = ('b3f7a1c9d4e2', 'b4e91a2f7c33')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
