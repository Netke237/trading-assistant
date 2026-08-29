"""add scheduled_scan_runs table

Revision ID: d4f6a8b2c913
Revises: c4a8f1d93b6e
Create Date: 2026-08-29 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd4f6a8b2c913'
down_revision = 'c4a8f1d93b6e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'scheduled_scan_runs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('schedule_entry_id', sa.String(), nullable=False),
        sa.Column('mode', sa.String(), nullable=False),
        sa.Column('fired_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('result_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_scheduled_scan_runs_schedule_entry_id'),
        'scheduled_scan_runs', ['schedule_entry_id'], unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_scheduled_scan_runs_schedule_entry_id'), table_name='scheduled_scan_runs')
    op.drop_table('scheduled_scan_runs')
