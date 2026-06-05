"""drawings text column

Revision ID: 3a503885d759
Revises: 349b7d1e8ceb
Create Date: 2026-06-05 12:43:35.476667

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3a503885d759'
down_revision = '349b7d1e8ceb'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('drawings', sa.Column('text', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('drawings', 'text')
