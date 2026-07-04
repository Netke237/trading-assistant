"""drop orphan kids-app schema

Removes the five orphaned tables (admins, children, quests, time_logs,
override_logs) that belonged to a kids' screen-time / chore-reward app scaffold.
They were the root "initial migration" of this backend but are referenced by no
router, service, or runtime model registry -- pure dead schema. The child<->quest
mutual foreign key (the FK cycle flagged by the schema-drift audit) is removed
along with them.

Idempotent: only drops tables that are actually present, so it is safe on any
database regardless of how far the orphan schema was applied.

Revision ID: a7f3e9b12c04
Revises: 9369a6166429
Create Date: 2026-07-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'a7f3e9b12c04'
down_revision = '9369a6166429'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    # Break the children<->quests FK cycle before dropping quests. Only Postgres
    # enforces this on DROP; SQLite has no ALTER DROP CONSTRAINT and does not need it.
    if bind.dialect.name != "sqlite" and "children" in existing:
        op.drop_constraint(
            "fk_children_current_quest_id_quests", "children", type_="foreignkey"
        )

    # Drop in dependency-safe order (leaf tables first).
    for table in ("override_logs", "time_logs", "quests", "children", "admins"):
        if table in existing:
            op.drop_table(table)


def downgrade() -> None:
    # Recreate the orphan schema exactly as the original initial migration did.
    # Postgres-oriented (uuid_generate_v4()/now() server defaults, ALTER ADD FK),
    # matching how these tables were originally defined.
    op.create_table(
        'admins',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('username', sa.String(length=50), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('sync_status', sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
        sa.UniqueConstraint('username')
    )
    op.create_index(op.f('ix_admins_username'), 'admins', ['username'], unique=False)

    op.create_table(
        'children',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('daily_time_budget', sa.Integer(), nullable=False),
        sa.Column('avatar_url', sa.String(length=500), nullable=True),
        sa.Column('parent_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('app_access_state', sa.String(length=20), nullable=False),
        sa.Column('current_quest_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('sync_status', sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(['parent_id'], ['admins.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_children_app_access_state'), 'children', ['app_access_state'], unique=False)
    op.create_index(op.f('ix_children_parent_id'), 'children', ['parent_id'], unique=False)
    op.create_index(op.f('ix_children_sync_status'), 'children', ['sync_status'], unique=False)

    op.create_table(
        'quests',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('child_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('assigned_admin_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('state', sa.String(length=30), nullable=False),
        sa.Column('proof_required', sa.Boolean(), nullable=False),
        sa.Column('points_reward', sa.Integer(), nullable=False),
        sa.Column('due_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sync_status', sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(['assigned_admin_id'], ['admins.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['child_id'], ['children.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_quests_assigned_admin_id'), 'quests', ['assigned_admin_id'], unique=False)
    op.create_index(op.f('ix_quests_child_id'), 'quests', ['child_id'], unique=False)
    op.create_index(op.f('ix_quests_state'), 'quests', ['state'], unique=False)
    op.create_index(op.f('ix_quests_sync_status'), 'quests', ['sync_status'], unique=False)

    op.create_foreign_key(
        'fk_children_current_quest_id_quests',
        'children', 'quests',
        ['current_quest_id'], ['id'],
        ondelete='SET NULL'
    )

    op.create_table(
        'time_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('child_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('budgeted_minutes', sa.Integer(), nullable=False),
        sa.Column('used_minutes', sa.Integer(), nullable=False),
        sa.Column('bonus_minutes', sa.Integer(), nullable=False),
        sa.Column('day_state', sa.String(length=20), nullable=False),
        sa.Column('reset_time', sa.Time(), nullable=True),
        sa.Column('sync_status', sa.String(length=20), nullable=False),
        sa.Column('calendar_import_state', sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(['child_id'], ['children.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_time_logs_calendar_import_state'), 'time_logs', ['calendar_import_state'], unique=False)
    op.create_index(op.f('ix_time_logs_child_id'), 'time_logs', ['child_id'], unique=False)
    op.create_index(op.f('ix_time_logs_date'), 'time_logs', ['date'], unique=False)
    op.create_index(op.f('ix_time_logs_day_state'), 'time_logs', ['day_state'], unique=False)
    op.create_index(op.f('ix_time_logs_sync_status'), 'time_logs', ['sync_status'], unique=False)

    op.create_table(
        'override_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('admin_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('child_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('override_type', sa.String(length=30), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('minutes_granted', sa.Integer(), nullable=True),
        sa.Column('previous_state', sa.String(length=50), nullable=False),
        sa.Column('new_state', sa.String(length=50), nullable=False),
        sa.Column('sync_status', sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(['admin_id'], ['admins.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['child_id'], ['children.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_override_logs_admin_id'), 'override_logs', ['admin_id'], unique=False)
    op.create_index(op.f('ix_override_logs_child_id'), 'override_logs', ['child_id'], unique=False)
    op.create_index(op.f('ix_override_logs_override_type'), 'override_logs', ['override_type'], unique=False)
    op.create_index(op.f('ix_override_logs_sync_status'), 'override_logs', ['sync_status'], unique=False)
