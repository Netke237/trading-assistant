"""add grading to watched_contracts

WATCHLIST-SCAN-CONTRACT-RULES: each starred contract keeps the grading inputs
Step 6 used when it was starred ({contract_rules, hold_min_days, hold_max_days,
stock_score}), so the Watchlist grades it with the scan's rules instead of
contract_rules.yaml.

Nullable, NO server default and NO backfill: NULL means "starred before this
change, or starred without grading", which the Watchlist shows as graded on
the YAML. Inventing a grading for old rows would claim rules nobody recorded.

WHY THIS MIGRATION IS REQUIRED: app/database.py creates tables with
Base.metadata.create_all(), which creates missing TABLES and does NOT add
columns to an existing one. Adding the column to the model without running this
migration makes every query on the model -- including the unchanged
GET /api/watched-contracts -- fail with a 500 on a live database, because the
SELECT names `grading`.

down_revision is f3d5c81b0a47, the single head on 2026-10-01.

Revision ID: a9c4e2f71d36
Revises: f3d5c81b0a47
Create Date: 2026-10-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a9c4e2f71d36'
down_revision = 'f3d5c81b0a47'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('watched_contracts') as batch_op:
        batch_op.add_column(sa.Column('grading', sa.JSON(none_as_null=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('watched_contracts') as batch_op:
        batch_op.drop_column('grading')
