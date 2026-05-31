"""add_watched_contracts

Revision ID: b1c2d3e4f5a6
Revises: e510ee3042ad
Create Date: 2026-05-27

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'b1c2d3e4f5a6'
down_revision = 'e510ee3042ad'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'watched_contracts',
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            server_default=sa.text('uuid_generate_v4()'),
            nullable=False,
        ),
        sa.Column('contract_id', sa.String(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('contract_id'),
    )
    op.create_index('ix_watched_contracts_contract_id', 'watched_contracts', ['contract_id'])


def downgrade() -> None:
    op.drop_index('ix_watched_contracts_contract_id', table_name='watched_contracts')
    op.drop_table('watched_contracts')
