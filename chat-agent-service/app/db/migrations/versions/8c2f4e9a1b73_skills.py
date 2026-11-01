"""agent skills: skills, skill_versions, skill_files, skill_usage, agents.skill_ids

Revision ID: 8c2f4e9a1b73
Revises: 50686a7bfc4c
Create Date: 2026-10-25 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '8c2f4e9a1b73'
down_revision = '50686a7bfc4c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('skills',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.String(length=128), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('latest_version', sa.Integer(), nullable=False),
    sa.Column('is_enabled', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'name', name='uq_skills_user_name')
    )
    op.create_index(op.f('ix_skills_user_id'), 'skills', ['user_id'], unique=False)
    op.create_table('skill_versions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('skill_id', sa.UUID(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('frontmatter', sa.JSON(), nullable=False),
    sa.Column('has_scripts', sa.Boolean(), nullable=False),
    sa.Column('total_bytes', sa.Integer(), nullable=False),
    sa.Column('checksum', sa.String(length=64), nullable=False),
    sa.Column('created_by', sa.String(length=128), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['skill_id'], ['skills.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('skill_id', 'version', name='uq_skill_versions_skill_version')
    )
    op.create_index(op.f('ix_skill_versions_skill_id'), 'skill_versions', ['skill_id'], unique=False)
    op.create_table('skill_files',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('skill_version_id', sa.UUID(), nullable=False),
    sa.Column('path', sa.String(length=512), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('mime', sa.String(length=128), nullable=False),
    sa.Column('storage_key', sa.String(length=1024), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['skill_version_id'], ['skill_versions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('skill_version_id', 'path', name='uq_skill_files_version_path')
    )
    op.create_index(op.f('ix_skill_files_skill_version_id'), 'skill_files', ['skill_version_id'], unique=False)
    op.create_table('skill_usage',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('skill_id', sa.UUID(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('agent_id', sa.UUID(), nullable=True),
    sa.Column('conversation_id', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.String(length=128), nullable=False),
    sa.Column('action', sa.String(length=16), nullable=False),
    sa.Column('detail', sa.String(length=512), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_skill_usage_skill_id'), 'skill_usage', ['skill_id'], unique=False)
    op.create_index(op.f('ix_skill_usage_conversation_id'), 'skill_usage', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_skill_usage_user_id'), 'skill_usage', ['user_id'], unique=False)
    # existing agents get an empty list (server_default only backfills; the ORM supplies the default afterwards)
    op.add_column('agents', sa.Column('skill_ids', sa.JSON(), server_default=sa.text("'[]'"), nullable=False))


def downgrade() -> None:
    op.drop_column('agents', 'skill_ids')
    op.drop_index(op.f('ix_skill_usage_user_id'), table_name='skill_usage')
    op.drop_index(op.f('ix_skill_usage_conversation_id'), table_name='skill_usage')
    op.drop_index(op.f('ix_skill_usage_skill_id'), table_name='skill_usage')
    op.drop_table('skill_usage')
    op.drop_index(op.f('ix_skill_files_skill_version_id'), table_name='skill_files')
    op.drop_table('skill_files')
    op.drop_index(op.f('ix_skill_versions_skill_id'), table_name='skill_versions')
    op.drop_table('skill_versions')
    op.drop_index(op.f('ix_skills_user_id'), table_name='skills')
    op.drop_table('skills')
    # No Postgres ENUMs are introduced by this migration, so there is no DROP TYPE to add.
