"""add portfolio history and equity snapshots

Revision ID: ad10598425a1
Revises: 4906fa45ce2c
Create Date: 2026-05-31 18:53:37.527127

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ad10598425a1'
down_revision = '4906fa45ce2c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Only the two new portfolio-history tables. Autogenerate also reported
    # unrelated drift (watched_contracts has its own migration; override_logs /
    # time_logs / NUMERIC->UUID belong to a different project sharing the dev DB)
    # which has been intentionally removed per the plan.
    op.create_table('closed_positions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('rec_id', sa.String(), nullable=False),
    sa.Column('symbol', sa.String(), nullable=False),
    sa.Column('contract', sa.String(), nullable=False),
    sa.Column('direction', sa.String(), nullable=False),
    sa.Column('entry_price', sa.Float(), nullable=False),
    sa.Column('entry_date', sa.String(), nullable=True),
    sa.Column('exit_price', sa.Float(), nullable=False),
    sa.Column('exit_date', sa.String(), nullable=False),
    sa.Column('qty_closed', sa.Integer(), nullable=False),
    sa.Column('realized_pnl_dollar', sa.Float(), nullable=False),
    sa.Column('realized_pnl_pct', sa.Float(), nullable=False),
    sa.Column('source', sa.String(), nullable=True),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_closed_positions_contract'), 'closed_positions', ['contract'], unique=False)
    op.create_index(op.f('ix_closed_positions_rec_id'), 'closed_positions', ['rec_id'], unique=False)
    op.create_table('equity_snapshots',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('snapshot_date', sa.String(), nullable=False),
    sa.Column('realized_cumulative', sa.Float(), nullable=False),
    sa.Column('open_value', sa.Float(), nullable=False),
    sa.Column('total_value', sa.Float(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_equity_snapshots_snapshot_date'), 'equity_snapshots', ['snapshot_date'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_equity_snapshots_snapshot_date'), table_name='equity_snapshots')
    op.drop_table('equity_snapshots')
    op.drop_index(op.f('ix_closed_positions_rec_id'), table_name='closed_positions')
    op.drop_index(op.f('ix_closed_positions_contract'), table_name='closed_positions')
    op.drop_table('closed_positions')
