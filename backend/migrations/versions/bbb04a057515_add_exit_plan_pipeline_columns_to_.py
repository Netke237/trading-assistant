"""add exit plan pipeline columns to portfolio positions

Revision ID: bbb04a057515
Revises: 28b49e5ff040
Create Date: 2026-08-26 13:18:57.146622

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'bbb04a057515'
down_revision = '28b49e5ff040'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # All additive ADD COLUMNs, no ordering dependency between them — Phase 0
    # scaffolding for the exit-plan pipeline
    # (docs/superpowers/plans/2026-08-26-exit-plan-pipeline.md). Business
    # logic that populates/consumes these lands in later phases.
    op.add_column('portfolio_positions', sa.Column('exit_plan', sa.JSON(), nullable=True))
    op.add_column('portfolio_positions', sa.Column('max_loss_override', sa.JSON(), nullable=True))
    op.add_column(
        'portfolio_positions',
        sa.Column('active_tp_method', sa.String(), nullable=False, server_default='ladder'),
    )
    op.add_column('portfolio_positions', sa.Column('resolved_tp_price', sa.Float(), nullable=True))
    op.add_column(
        'portfolio_positions',
        sa.Column('resolved_tp_updated_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'portfolio_positions',
        sa.Column('alert_overrides', sa.JSON(), nullable=True, server_default='{}'),
    )


def downgrade() -> None:
    op.drop_column('portfolio_positions', 'alert_overrides')
    op.drop_column('portfolio_positions', 'resolved_tp_updated_at')
    op.drop_column('portfolio_positions', 'resolved_tp_price')
    op.drop_column('portfolio_positions', 'active_tp_method')
    op.drop_column('portfolio_positions', 'max_loss_override')
    op.drop_column('portfolio_positions', 'exit_plan')
