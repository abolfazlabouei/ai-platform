"""add kb_chunks

Revision ID: 4effe3a49ef3
Revises: 0c4ba1c1d5e0
Create Date: 2026-09-28 17:18:39.988416
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '4effe3a49ef3'
down_revision = '0c4ba1c1d5e0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('kb_chunks',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('knowledge_base_id', sa.UUID(), nullable=False),
    sa.Column('file_id', sa.UUID(), nullable=False),
    sa.Column('chunk_id', sa.UUID(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('type', sa.String(length=32), nullable=True),
    sa.Column('order_index', sa.Integer(), nullable=True),
    sa.Column('content_tsv', postgresql.TSVECTOR(), sa.Computed("to_tsvector('simple', content)", persisted=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['knowledge_base_id'], ['knowledge_bases.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_kb_chunks_file_id'), 'kb_chunks', ['file_id'], unique=False)
    op.create_index(op.f('ix_kb_chunks_knowledge_base_id'), 'kb_chunks', ['knowledge_base_id'], unique=False)
    op.create_index('ix_kb_chunks_content_tsv', 'kb_chunks', ['content_tsv'], unique=False, postgresql_using='gin')


def downgrade() -> None:
    op.drop_index('ix_kb_chunks_content_tsv', table_name='kb_chunks')
    op.drop_index(op.f('ix_kb_chunks_knowledge_base_id'), table_name='kb_chunks')
    op.drop_index(op.f('ix_kb_chunks_file_id'), table_name='kb_chunks')
    op.drop_table('kb_chunks')
