"""drop orphan updated_at from portfolio_positions

Revision ID: 41919f210c18
Revises: f14c8c7e35e8
Create Date: 2026-07-04 17:27:17.695830

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '41919f210c18'
down_revision = 'f14c8c7e35e8'
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    # `updated_at` is a vestigial column present only on databases (e.g. the dev
    # Postgres) where portfolio_positions was once built from an older model that
    # inherited the timestamp mixin. The current model has no `updated_at`, no
    # migration adds it, and nothing in the app reads it. Drop it where present so
    # every database matches the model; this is a no-op where the column is absent
    # (SQLite dev.db, and any freshly-migrated database).
    if _has_column("portfolio_positions", "updated_at"):
        op.drop_column("portfolio_positions", "updated_at")


def downgrade() -> None:
    if not _has_column("portfolio_positions", "updated_at"):
        op.add_column(
            "portfolio_positions",
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
