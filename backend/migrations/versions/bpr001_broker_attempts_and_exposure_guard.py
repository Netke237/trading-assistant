"""Add broker attempts and the exposure guard.

Does not invent attempts for orders placed before this revision. Portfolio
prepared-order columns stay null on existing rows. Daily-risk tables are untouched.

Revision ID: bpr001
Revises: a93b8d24f760
"""
from alembic import op
import sqlalchemy as sa

revision = "bpr001"
down_revision = "a93b8d24f760"
branch_labels = None
depends_on = None

def _unresolved():
    return sa.text("state IN ('preparing', 'dispatching', 'outcome-unknown')")


def upgrade():
    op.create_table(
        "broker_attempts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("payload_canonical", sa.Text(), nullable=False),
        sa.Column("payload_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("broker_response", sa.Text(), nullable=True),
        sa.Column("broker_order_id", sa.String(), nullable=True),
        sa.Column("broker_status", sa.String(), nullable=True),
        sa.Column("saved_rec_id", sa.String(), nullable=True),
        sa.Column("verification_outcome", sa.String(), nullable=True),
        sa.Column("verification_note", sa.Text(), nullable=True),
        sa.Column("verification_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatch_authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('preparing', 'dispatching', 'proven-not-submitted', 'submitted', 'filled', 'outcome-unknown')",
            name="ck_broker_attempts_state",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_broker_attempts_payload_fingerprint", "broker_attempts", ["payload_fingerprint"])
    op.create_index(
        "uq_broker_attempts_unresolved_fingerprint",
        "broker_attempts",
        ["payload_fingerprint"],
        unique=True,
        sqlite_where=_unresolved(),
        postgresql_where=_unresolved(),
    )
    op.create_table(
        "exposure_guards",
        sa.Column("id", sa.String(length=16), nullable=False),
        sa.Column("guarded", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "exposure_holds",
        sa.Column("attempt_id", sa.String(), nullable=False),
        sa.Column("instrument", sa.String(), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("limit_price", sa.String(), nullable=False),
        sa.Column("multiplier", sa.BigInteger(), nullable=False),
        sa.Column("notional", sa.String(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("effect", sa.String(), nullable=True),
        sa.Column("saved_rec_id", sa.String(), nullable=True),
        sa.Column("coverage_quantity", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("attempt_id"),
    )
    op.add_column("portfolio_positions", sa.Column("prepared_order", sa.JSON(), nullable=True))
    op.add_column("portfolio_positions", sa.Column("order_attempt_id", sa.String(), nullable=True))
    op.create_index("ix_portfolio_positions_order_attempt_id", "portfolio_positions", ["order_attempt_id"])


def downgrade():
    op.drop_index("ix_portfolio_positions_order_attempt_id", table_name="portfolio_positions")
    op.drop_column("portfolio_positions", "order_attempt_id")
    op.drop_column("portfolio_positions", "prepared_order")
    op.drop_table("exposure_holds")
    op.drop_table("exposure_guards")
    op.drop_index("uq_broker_attempts_unresolved_fingerprint", table_name="broker_attempts")
    op.drop_index("ix_broker_attempts_payload_fingerprint", table_name="broker_attempts")
    op.drop_table("broker_attempts")
