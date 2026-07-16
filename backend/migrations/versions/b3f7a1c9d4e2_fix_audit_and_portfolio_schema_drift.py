"""fix audit_events and portfolio_positions schema drift

Revision ID: b3f7a1c9d4e2
Revises: a7f3e9b12c04
Create Date: 2026-07-15

Closes Postgres-only correctness bugs invisible on the SQLite dev fallback.
These weren't caught in dev because the SQLite fallback never runs Alembic at
all — it bootstraps via `Base.metadata.create_all()` (app/database.py:35),
which always reflects the current ORM model shape directly, so type/nullable/
unique drift between a migration and the model can only surface on Postgres:

1. audit_events.recommendation_id was created as UUID but the ORM model (and
   every write site in app/services/audit.py) always uses a non-UUID rec_id
   string like "REC-20260715-AB12CD34" — every approve/reject/override write
   fails with "invalid input syntax for type uuid" on real Postgres.
2. audit_events.rec_id was created nullable with no index, but the ORM model
   declares it `nullable=False, index=True`.
3. portfolio_positions.rec_id/.contract were never given the UNIQUE constraint
   the ORM model declares, and .entry_date was created as DateTime while the
   model (and every write site) treats it as a plain ISO string.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'b3f7a1c9d4e2'
down_revision = 'a7f3e9b12c04'
branch_labels = None
depends_on = None


def _check_upgrade_preconditions() -> None:
    """The tables this migration tightens were originally created with looser
    constraints (audit_events.recommendation_id nullable; portfolio_positions
    rec_id/contract nullable and not unique) — see
    16febdf31dd2_add_persistence_tables.py. If any real rows violate what
    we're about to enforce, raise a clear, actionable error up front instead
    of letting a raw Postgres UniqueViolation/NotNullViolation surface
    mid-migration with no guidance."""
    bind = op.get_bind()

    null_recommendation_id = bind.execute(sa.text(
        "SELECT count(*) FROM audit_events WHERE recommendation_id IS NULL"
    )).scalar()
    if null_recommendation_id:
        raise RuntimeError(
            f"{null_recommendation_id} audit_events row(s) have NULL recommendation_id — "
            "cannot apply NOT NULL. Back these rows up and either delete them "
            "or backfill recommendation_id from rec_id before re-running this migration."
        )

    null_audit_rec_id = bind.execute(sa.text(
        "SELECT count(*) FROM audit_events WHERE rec_id IS NULL"
    )).scalar()
    if null_audit_rec_id:
        raise RuntimeError(
            f"{null_audit_rec_id} audit_events row(s) have NULL rec_id — "
            "cannot apply NOT NULL. Back these rows up and either delete them "
            "or backfill rec_id before re-running this migration."
        )

    null_rec_id = bind.execute(sa.text(
        "SELECT count(*) FROM portfolio_positions WHERE rec_id IS NULL"
    )).scalar()
    if null_rec_id:
        raise RuntimeError(
            f"{null_rec_id} portfolio_positions row(s) have NULL rec_id — "
            "cannot apply NOT NULL. Back these rows up and either delete them "
            "or assign a rec_id before re-running this migration."
        )

    dup_rec_id = bind.execute(sa.text(
        "SELECT rec_id, count(*) FROM portfolio_positions "
        "GROUP BY rec_id HAVING count(*) > 1"
    )).fetchall()
    if dup_rec_id:
        raise RuntimeError(
            f"Duplicate rec_id values in portfolio_positions: {dup_rec_id} — "
            "cannot apply UNIQUE. Resolve the duplicates (this is likely the "
            "double-close/double-insert race also fixed in this audit pass) "
            "before re-running this migration."
        )

    dup_contract = bind.execute(sa.text(
        "SELECT contract, count(*) FROM portfolio_positions "
        "GROUP BY contract HAVING count(*) > 1"
    )).fetchall()
    if dup_contract:
        raise RuntimeError(
            f"Duplicate contract values in portfolio_positions: {dup_contract} — "
            "cannot apply UNIQUE. Resolve the duplicates before re-running this migration."
        )


def upgrade() -> None:
    _check_upgrade_preconditions()

    # ── audit_events.recommendation_id: UUID -> String ─────────────────────────
    op.alter_column(
        'audit_events', 'recommendation_id',
        existing_type=postgresql.UUID(as_uuid=True),
        type_=sa.String(),
        postgresql_using='recommendation_id::text',
        nullable=False,
    )

    # ── audit_events.rec_id: add missing NOT NULL + index ───────────────────────
    op.alter_column('audit_events', 'rec_id', existing_type=sa.String(), nullable=False)
    op.create_index('ix_audit_events_rec_id', 'audit_events', ['rec_id'])

    # ── portfolio_positions.entry_date: DateTime -> String ──────────────────────
    # The table is empty at migration time (verified), so this cast is a
    # formality, not a real data-preserving conversion: `entry_date::text` on a
    # timestamptz produces Postgres's native format ("2026-07-15 09:30:00+00"),
    # NOT the app's actual "YYYY-MM-DD" string convention. A real backfill on a
    # populated table would need an explicit to_char() reformat, not a bare cast.
    op.alter_column(
        'portfolio_positions', 'entry_date',
        existing_type=sa.DateTime(timezone=True),
        type_=sa.String(),
        postgresql_using='entry_date::text',
        nullable=False,
    )
    # ALTER COLUMN ... TYPE carries the old DateTime column's DEFAULT now()
    # (a timestamptz expression) forward onto the new varchar column instead of
    # dropping it. The ORM model declares no default at all — drop it explicitly.
    op.alter_column('portfolio_positions', 'entry_date', server_default=None)

    # ── portfolio_positions.rec_id / .contract: add missing UNIQUE + NOT NULL ──
    op.alter_column('portfolio_positions', 'rec_id', existing_type=sa.String(), nullable=False)
    op.create_unique_constraint('uq_portfolio_positions_rec_id', 'portfolio_positions', ['rec_id'])
    op.create_unique_constraint('uq_portfolio_positions_contract', 'portfolio_positions', ['contract'])


def downgrade() -> None:
    op.drop_constraint('uq_portfolio_positions_contract', 'portfolio_positions', type_='unique')
    op.drop_constraint('uq_portfolio_positions_rec_id', 'portfolio_positions', type_='unique')
    op.alter_column('portfolio_positions', 'rec_id', existing_type=sa.String(), nullable=True)

    op.alter_column(
        'portfolio_positions', 'entry_date',
        existing_type=sa.String(),
        type_=sa.DateTime(timezone=True),
        postgresql_using='entry_date::timestamptz',
        server_default=sa.text('now()'),
        nullable=False,
    )

    op.drop_index('ix_audit_events_rec_id', table_name='audit_events')
    op.alter_column('audit_events', 'rec_id', existing_type=sa.String(), nullable=True)

    op.alter_column(
        'audit_events', 'recommendation_id',
        existing_type=sa.String(),
        type_=postgresql.UUID(as_uuid=True),
        postgresql_using='recommendation_id::uuid',
        nullable=True,
    )
