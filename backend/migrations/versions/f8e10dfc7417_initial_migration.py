"""initial migration

Revision ID: f8e10dfc7417
Revises: 
Create Date: 2026-04-23 23:53:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'f8e10dfc7417'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create admins table
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

    # Create children table
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

    # Create quests table
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

    # Add FK from children to quests (after quests table exists)
    op.create_foreign_key(
        'fk_children_current_quest_id_quests',
        'children', 'quests',
        ['current_quest_id'], ['id'],
        ondelete='SET NULL'
    )

    # Create time_logs table
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

    # Create override_logs table
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


def downgrade() -> None:
    op.drop_table('override_logs')
    op.drop_table('time_logs')
    op.drop_constraint('fk_children_current_quest_id_quests', 'children', type_='foreignkey')
    op.drop_table('quests')
    op.drop_table('children')
    op.drop_table('admins')
