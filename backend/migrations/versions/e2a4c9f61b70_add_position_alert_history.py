"""add position_alert_history table

Revision ID: e2a4c9f61b70
Revises: d92f6a1c8e37
Create Date: 2026-08-05

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'e2a4c9f61b70'
down_revision = 'd92f6a1c8e37'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'position_alert_history',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('rec_id', sa.String(), nullable=False),
        sa.Column('symbol', sa.String(), nullable=False),
        sa.Column('alert_type', sa.String(), nullable=False),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('price', sa.Float(), nullable=True),
        sa.Column('reference_value', sa.Float(), nullable=True),
        sa.Column('reference_kind', sa.String(), nullable=True),
        sa.Column('direction', sa.String(), nullable=True),
        sa.Column('contract', sa.String(), nullable=True),
        sa.Column('note', sa.String(), nullable=True),
        sa.Column('triggered_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_position_alert_history_rec_id_alert_type',
        'position_alert_history', ['rec_id', 'alert_type'], unique=False,
    )
    op.create_index(
        op.f('ix_position_alert_history_rec_id'),
        'position_alert_history', ['rec_id'], unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_position_alert_history_rec_id'), table_name='position_alert_history')
    op.drop_index('ix_position_alert_history_rec_id_alert_type', table_name='position_alert_history')
    op.drop_table('position_alert_history')
