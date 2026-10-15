"""Add immutable backtest evidence and expiry tombstones."""
from alembic import op
import sqlalchemy as sa

revision = 'b47d68e91a20'
down_revision = 'a93b8d24f760'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('backtest_artifacts',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('schema_version', sa.Integer(), nullable=False),
        sa.Column('symbol', sa.String(), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.Column('expires_at', sa.Float(), nullable=False),
        sa.Column('payload_json', sa.Text(), nullable=True), sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_backtest_artifacts_expires_at', 'backtest_artifacts', ['expires_at'])


def downgrade():
    op.drop_index('ix_backtest_artifacts_expires_at', table_name='backtest_artifacts')
    op.drop_table('backtest_artifacts')
