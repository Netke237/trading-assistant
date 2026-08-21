"""backfill zero stop and structural_stop to null

Revision ID: 28b49e5ff040
Revises: a9c3f5d1e872
Create Date: 2026-08-21 18:55:27.189646

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '28b49e5ff040'
down_revision = 'a9c3f5d1e872'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A stock price is never <= 0, so any row that ended up with stop=0 or
    # structural_stop=0 (the exact bug the app-level PATCH/POST fix in this
    # same change closes) can only be a stale artifact of that bug -- never a
    # legitimate value. STOP_REACHED / STRUCTURAL_STOP_BREACHED gate on
    # `is not None`, not `> 0`, so left in place a Bearish position with
    # either field at 0 fires a real notification on every sustained cycle.
    op.execute(
        "UPDATE portfolio_positions SET stop = NULL WHERE stop = 0"
    )
    op.execute(
        "UPDATE portfolio_positions SET structural_stop = NULL WHERE structural_stop = 0"
    )


def downgrade() -> None:
    # One-way data fix -- a 0 was never a legitimate value, so there is
    # nothing correct to restore it to.
    pass
