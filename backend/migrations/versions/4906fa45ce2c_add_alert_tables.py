"""add alert tables

Revision ID: 4906fa45ce2c
Revises: b1c2d3e4f5a6
Create Date: 2026-05-27 22:54:36.717429

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4906fa45ce2c'
down_revision = 'b1c2d3e4f5a6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'alert_rules',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('user_id', sa.String(64), nullable=False, server_default=sa.text("'default'")),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('symbol', sa.String(10), nullable=False),
        sa.Column('interval', sa.String(10), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('TRUE')),
        sa.Column('rule_json', sa.Text(), nullable=False),
        sa.Column('cooldown_minutes', sa.Integer(), nullable=False, server_default=sa.text('60')),
        sa.Column('expiry_date', sa.Text(), nullable=True),
        sa.Column('created_at', sa.Text(), nullable=False),
        sa.Column('last_triggered_at', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_alert_rules_symbol'), 'alert_rules', ['symbol'], unique=False)
    op.create_index(op.f('ix_alert_rules_user_id'), 'alert_rules', ['user_id'], unique=False)

    op.create_table(
        'alert_history',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('rule_id', sa.String(36), nullable=False),
        sa.Column('symbol', sa.String(10), nullable=True),
        sa.Column('interval', sa.String(10), nullable=True),
        sa.Column('triggered_at', sa.Text(), nullable=False),
        sa.Column('candle_json', sa.Text(), nullable=False),
        sa.Column('trigger_values', sa.Text(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['rule_id'], ['alert_rules.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_alert_history_rule_id'), 'alert_history', ['rule_id'], unique=False)
    op.create_index(op.f('ix_alert_history_symbol'), 'alert_history', ['symbol'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_alert_history_symbol'), table_name='alert_history')
    op.drop_index(op.f('ix_alert_history_rule_id'), table_name='alert_history')
    op.drop_table('alert_history')
    op.drop_index(op.f('ix_alert_rules_user_id'), table_name='alert_rules')
    op.drop_index(op.f('ix_alert_rules_symbol'), table_name='alert_rules')
    op.drop_table('alert_rules')
