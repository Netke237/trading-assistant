"""add journal_entries table

Revision ID: 2bf3bf834b29
Revises: d4f6a8b2c913
Create Date: 2026-08-30 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2bf3bf834b29'
down_revision = 'd4f6a8b2c913'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'journal_entries',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('user_id', sa.String(64), nullable=False, server_default=sa.text("'default'")),
        sa.Column('entry_type', sa.String(10), nullable=False),
        sa.Column('entry_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('symbol', sa.String(10), nullable=True),
        sa.Column('instrument_type', sa.String(10), nullable=True),
        sa.Column('direction', sa.String(10), nullable=True),
        sa.Column('entry_price', sa.Float(), nullable=True),
        sa.Column('exit_price', sa.Float(), nullable=True),
        sa.Column('position_size', sa.Float(), nullable=True),
        sa.Column('stop_loss', sa.Float(), nullable=True),
        sa.Column('risk_dollars', sa.Float(), nullable=True),
        sa.Column('net_pnl', sa.Float(), nullable=True),
        sa.Column('thesis', sa.Text(), nullable=True),
        sa.Column('strategy_tag', sa.String(64), nullable=True),
        sa.Column('mistake_tags', sa.JSON(), nullable=True),
        sa.Column('execution_grade', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(10), nullable=True),
        sa.Column('lessons_learned', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('position_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_journal_entries_user_id_entry_date',
        'journal_entries', ['user_id', 'entry_date'], unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_journal_entries_user_id_entry_date', table_name='journal_entries')
    op.drop_table('journal_entries')
