"""Add the ingestion_run table: the persisted last-run summary (HISTORY-INCREMENTAL-NIGHTLY C1b).

Revision ID: d6a2f9c4e017
Revises: b7d4e2a9c816

down_revision is b7d4e2a9c816, the single head on 2026-11-12. A new table only; no
change to existing tables or rows.
"""
from alembic import op
import sqlalchemy as sa

revision = "d6a2f9c4e017"
down_revision = "b7d4e2a9c816"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ingestion_run",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_table("ingestion_run")
