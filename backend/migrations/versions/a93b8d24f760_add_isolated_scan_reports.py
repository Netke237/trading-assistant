"""Add isolated scan report records without changing legacy evidence.

Revision ID: a93b8d24f760
Revises: e7b2d4a91c58
"""
from alembic import op
import sqlalchemy as sa

revision = 'a93b8d24f760'
down_revision = 'e7b2d4a91c58'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('scan_reports',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('category', sa.String(), nullable=False),
        sa.Column('generation', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('envelope_json', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('id'), sa.UniqueConstraint('category', 'generation'))
    op.create_index('ix_scan_reports_category', 'scan_reports', ['category'])
    op.create_table('scan_report_heads',
        sa.Column('category', sa.String(), nullable=False),
        sa.Column('generation', sa.Integer(), nullable=False),
        sa.Column('latest_id', sa.String(), nullable=True),
        sa.Column('usable_id', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('category'))


def downgrade():
    op.drop_table('scan_report_heads')
    op.drop_index('ix_scan_reports_category', table_name='scan_reports')
    op.drop_table('scan_reports')
