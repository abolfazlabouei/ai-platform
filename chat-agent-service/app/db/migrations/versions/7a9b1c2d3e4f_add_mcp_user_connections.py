"""add mcp_user_connections

Revision ID: 7a9b1c2d3e4f
Revises: 50686a7bfc4c
Create Date: 2026-09-11 17:35:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '7a9b1c2d3e4f'
down_revision = '50686a7bfc4c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'mcp_user_connections',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('mcp_server_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.String(length=128), nullable=False),
        sa.Column('access_token_encrypted', sa.Text(), nullable=False),
        sa.Column('refresh_token_encrypted', sa.Text(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('scopes', sa.String(length=1024), nullable=True),
        sa.Column('status', sa.Enum('CONNECTED', 'EXPIRED', 'DISCONNECTED', name='oauth_connection_status'), nullable=False),
        sa.Column('last_error', sa.String(length=2048), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['mcp_server_id'], ['mcp_servers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('mcp_server_id', 'user_id', name='uq_mcp_server_user'),
    )
    op.create_index(op.f('ix_mcp_user_connections_mcp_server_id'), 'mcp_user_connections', ['mcp_server_id'], unique=False)
    op.create_index(op.f('ix_mcp_user_connections_user_id'), 'mcp_user_connections', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_mcp_user_connections_user_id'), table_name='mcp_user_connections')
    op.drop_index(op.f('ix_mcp_user_connections_mcp_server_id'), table_name='mcp_user_connections')
    op.drop_table('mcp_user_connections')

    sa.Enum(name='oauth_connection_status').drop(op.get_bind(), checkfirst=True)
