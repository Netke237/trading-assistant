"""Persist daily opening risk and gross realized losses."""
from alembic import op
import sqlalchemy as sa
revision = 'f62a9e1b4c70'
down_revision = 'a9c4e2f71d36'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('daily_risk_budgets', sa.Column('day', sa.String(10), primary_key=True), sa.Column('reserved_cents', sa.BigInteger(), nullable=False), sa.Column('loss_cents', sa.BigInteger(), nullable=False), sa.CheckConstraint('reserved_cents >= 0 AND loss_cents >= 0'))
    op.create_table('daily_risk_attempts', sa.Column('id', sa.String(64), primary_key=True), sa.Column('day', sa.String(10), nullable=False), sa.Column('reserved_cents', sa.BigInteger(), nullable=False), sa.Column('state', sa.String(20), nullable=False), sa.Column('outcome', sa.String(), nullable=False), sa.Column('instrument', sa.String(), nullable=False), sa.Column('source', sa.String(), nullable=False), sa.Column('quantity', sa.BigInteger(), nullable=False), sa.Column('price', sa.String(), nullable=False), sa.Column('multiplier', sa.BigInteger(), nullable=False))
    op.create_index('ix_daily_risk_attempts_day', 'daily_risk_attempts', ['day'])
    op.create_table('daily_risk_losses', sa.Column('closed_id', sa.String(64), primary_key=True), sa.Column('day', sa.String(10), nullable=False), sa.Column('loss_cents', sa.BigInteger(), nullable=False))


def downgrade():
    op.drop_table('daily_risk_losses')
    op.drop_index('ix_daily_risk_attempts_day', table_name='daily_risk_attempts')
    op.drop_table('daily_risk_attempts')
    op.drop_table('daily_risk_budgets')
