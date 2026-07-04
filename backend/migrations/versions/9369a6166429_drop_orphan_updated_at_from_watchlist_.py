"""drop orphan updated_at from watchlist_symbols

Revision ID: 9369a6166429
Revises: 41919f210c18
Create Date: 2026-07-04 20:39:56.663849

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9369a6166429'
down_revision = '41919f210c18'
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    # Same vestigial timestamp-mixin remnant as portfolio_positions: the current
    # watchlist_symbols model declares no `updated_at`, no migration adds it, and
    # nothing reads it — but it lingers on databases built from an older model
    # (the dev Postgres). Drop where present; no-op where absent (SQLite, fresh DBs).
    if _has_column("watchlist_symbols", "updated_at"):
        op.drop_column("watchlist_symbols", "updated_at")


def downgrade() -> None:
    if not _has_column("watchlist_symbols", "updated_at"):
        op.add_column(
            "watchlist_symbols",
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
