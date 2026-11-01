"""init

Revision ID: 5b1e7c2d9a10
Revises: 
Create Date: 2026-10-24 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '5b1e7c2d9a10'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('sandbox_sessions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('conversation_id', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.String(length=128), nullable=False),
    sa.Column('language', sa.String(length=16), nullable=False),
    sa.Column('image', sa.String(length=128), nullable=False),
    sa.Column('container_id', sa.String(length=80), nullable=True),
    sa.Column('status', sa.Enum('CREATING', 'READY', 'BUSY', 'TERMINATED', 'ERROR', name='sandbox_session_status'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('terminated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('terminate_reason', sa.String(length=64), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sandbox_sessions_user_id'), 'sandbox_sessions', ['user_id'], unique=False)
    op.create_index('uq_sandbox_sessions_active_conversation', 'sandbox_sessions', ['conversation_id'], unique=True, postgresql_where=sa.text("status != 'TERMINATED'"))
    op.create_table('sandbox_executions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('session_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.String(length=128), nullable=False),
    sa.Column('language', sa.String(length=16), nullable=False),
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('exit_code', sa.Integer(), nullable=True),
    sa.Column('timed_out', sa.Boolean(), nullable=False),
    sa.Column('oom_killed', sa.Boolean(), nullable=False),
    sa.Column('stdout_bytes', sa.Integer(), nullable=False),
    sa.Column('stderr_bytes', sa.Integer(), nullable=False),
    sa.Column('truncated', sa.Boolean(), nullable=False),
    sa.Column('duration_ms', sa.Integer(), nullable=False),
    sa.Column('artifact_keys', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['sandbox_sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sandbox_executions_session_id'), 'sandbox_executions', ['session_id'], unique=False)
    op.create_index(op.f('ix_sandbox_executions_user_id'), 'sandbox_executions', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_sandbox_executions_user_id'), table_name='sandbox_executions')
    op.drop_index(op.f('ix_sandbox_executions_session_id'), table_name='sandbox_executions')
    op.drop_table('sandbox_executions')
    op.drop_index('uq_sandbox_sessions_active_conversation', table_name='sandbox_sessions', postgresql_where=sa.text("status != 'TERMINATED'"))
    op.drop_index(op.f('ix_sandbox_sessions_user_id'), table_name='sandbox_sessions')
    op.drop_table('sandbox_sessions')

    # --- manually added: Alembic's autogenerate does not emit DROP TYPE for
    # Postgres ENUMs when the owning table is dropped, so without this a
    # downgrade -> upgrade roundtrip fails with "type already exists". ---
    sa.Enum(name='sandbox_session_status').drop(op.get_bind(), checkfirst=True)
