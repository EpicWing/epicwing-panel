"""containers

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-09 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('containers',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('node_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('docker_name', sa.String(length=63), nullable=False),
    sa.Column('image', sa.String(length=255), nullable=False),
    sa.Column('host_port', sa.Integer(), nullable=False),
    sa.Column('container_port', sa.Integer(), nullable=False),
    sa.Column('protocol', sa.String(length=3), nullable=False),
    sa.Column('memory_mb', sa.Integer(), nullable=False),
    sa.Column('cpus', sa.Float(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('last_error', sa.String(length=1024), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['node_id'], ['nodes.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('docker_name'),
    sa.UniqueConstraint('node_id', 'host_port', 'protocol', name='uq_containers_node_port')
    )
    op.create_index(op.f('ix_containers_node_id'), 'containers', ['node_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_containers_node_id'), table_name='containers')
    op.drop_table('containers')
