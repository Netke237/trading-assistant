"""Add target_first_hit_at to open and closed positions (PORTFOLIO-ALERT-ACTION, #672).

Revision ID: a7f3c2d9e1b4
Revises: e3c7a1f5b209

down_revision is e3c7a1f5b209, the single head on 2026-11-27. One nullable
DateTime(timezone=True) column on portfolio_positions and on closed_positions,
no server default. It records when the position's target was first reached
(the first TP_HIT fire), so the History flag "Reached target, closed at a
loss" survives the pruning of position_alert_history.

Back-fill from the history rows that survive retention:
- open rows: MIN(triggered_at) of the rec_id's TP_HIT rows;
- closed rows: MIN(triggered_at) of the rec_id's TP_HIT rows with
  triggered_at <= closed_at (a fire after the close says nothing about that
  trade; a row with no closed_at cannot be checked and stays NULL).
A row with no surviving TP_HIT history stays NULL (no flag). The correlated
UPDATE is plain SQL that runs unchanged on SQLite and PostgreSQL. On SQLite
both timestamps are SQLAlchemy's fixed-width UTC strings, so the comparison
and MIN order like the instants they encode.

Downgrade drops both columns inside batch_alter_table (SQLite needs batch mode
to drop a column).
"""
from alembic import op
import sqlalchemy as sa

revision = "a7f3c2d9e1b4"
down_revision = "e3c7a1f5b209"
branch_labels = None
depends_on = None

_COLUMN = "target_first_hit_at"


def upgrade():
    op.add_column("portfolio_positions",
                  sa.Column(_COLUMN, sa.DateTime(timezone=True), nullable=True))
    op.add_column("closed_positions",
                  sa.Column(_COLUMN, sa.DateTime(timezone=True), nullable=True))

    op.execute(
        "UPDATE portfolio_positions SET target_first_hit_at = ("
        " SELECT MIN(h.triggered_at) FROM position_alert_history h"
        " WHERE h.rec_id = portfolio_positions.rec_id AND h.alert_type = 'TP_HIT')"
    )
    op.execute(
        "UPDATE closed_positions SET target_first_hit_at = ("
        " SELECT MIN(h.triggered_at) FROM position_alert_history h"
        " WHERE h.rec_id = closed_positions.rec_id AND h.alert_type = 'TP_HIT'"
        " AND h.triggered_at <= closed_positions.closed_at)"
    )


def downgrade():
    with op.batch_alter_table("closed_positions") as batch:
        batch.drop_column(_COLUMN)
    with op.batch_alter_table("portfolio_positions") as batch:
        batch.drop_column(_COLUMN)
