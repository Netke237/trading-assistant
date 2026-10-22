"""Add the provider_request_log usage ledger (HISTORY-INCREMENTAL-NIGHTLY A1).

Revision ID: e5c1a7d3b902
Revises: 35c19d72ef80

down_revision is 35c19d72ef80, the single head on 2026-10-21.
"""
from alembic import op
import sqlalchemy as sa

revision = "e5c1a7d3b902"
down_revision = "35c19d72ef80"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "provider_request_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol", sa.String(16), nullable=True),
        sa.Column("response_bytes", sa.BigInteger(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("caller", sa.String(16), nullable=False),
    )
    op.create_index("ix_provider_request_log_provider_requested_at",
                    "provider_request_log", ["provider", "requested_at"])


def downgrade():
    op.drop_index("ix_provider_request_log_provider_requested_at",
                  table_name="provider_request_log")
    op.drop_table("provider_request_log")
