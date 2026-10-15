"""Join the history-basis head with main's migration head.

The history branch added a6a5b5d01fa5 on top of a93b8d24f760. Main later
merged its own fork of that same parent at c29a451f911c. The two branches
touch disjoint tables. This revision makes no schema change.

Revision ID: 35c19d72ef80
Revises: a6a5b5d01fa5, c29a451f911c
Create Date: 2026-10-15 00:00:00.000000

"""

# revision identifiers, used by Alembic.
revision = "35c19d72ef80"
down_revision = ("a6a5b5d01fa5", "c29a451f911c")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
