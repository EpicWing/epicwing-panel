"""servers, eggs und allocations

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('nests',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('eggs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('nest_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=False),
    sa.Column('docker_image', sa.String(length=255), nullable=False),
    sa.Column('startup', sa.String(length=2048), nullable=False),
    sa.Column('stop_command', sa.String(length=255), nullable=False),
    sa.Column('install_script', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['nest_id'], ['nests.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('nest_id', 'name', name='uq_eggs_nest_name')
    )
    op.create_index(op.f('ix_eggs_nest_id'), 'eggs', ['nest_id'], unique=False)
    op.create_table('egg_variables',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('egg_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('env_variable', sa.String(length=64), nullable=False),
    sa.Column('default_value', sa.String(length=1024), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=False),
    sa.Column('user_editable', sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.ForeignKeyConstraint(['egg_id'], ['eggs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('egg_id', 'env_variable', name='uq_egg_variables_env')
    )
    op.create_index(op.f('ix_egg_variables_egg_id'), 'egg_variables', ['egg_id'], unique=False)
    op.create_table('servers',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=False),
    sa.Column('owner_id', sa.Uuid(), nullable=False),
    sa.Column('node_id', sa.Uuid(), nullable=False),
    sa.Column('egg_id', sa.Uuid(), nullable=False),
    sa.Column('image', sa.String(length=255), nullable=False),
    sa.Column('startup', sa.String(length=2048), nullable=False),
    sa.Column('memory_mb', sa.Integer(), nullable=False),
    sa.Column('cpus', sa.Float(), nullable=False),
    sa.Column('disk_mb', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('last_error', sa.String(length=1024), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['egg_id'], ['eggs.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['node_id'], ['nodes.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_servers_egg_id'), 'servers', ['egg_id'], unique=False)
    op.create_index(op.f('ix_servers_node_id'), 'servers', ['node_id'], unique=False)
    op.create_index(op.f('ix_servers_owner_id'), 'servers', ['owner_id'], unique=False)
    op.create_table('allocations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('node_id', sa.Uuid(), nullable=False),
    sa.Column('ip', sa.String(length=45), nullable=False),
    sa.Column('port', sa.Integer(), nullable=False),
    sa.Column('server_id', sa.Uuid(), nullable=True),
    sa.Column('is_primary', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['node_id'], ['nodes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['server_id'], ['servers.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('node_id', 'ip', 'port', name='uq_allocations_node_ip_port')
    )
    op.create_index(op.f('ix_allocations_node_id'), 'allocations', ['node_id'], unique=False)
    op.create_index(op.f('ix_allocations_server_id'), 'allocations', ['server_id'], unique=False)
    op.create_table('server_variables',
    sa.Column('server_id', sa.Uuid(), nullable=False),
    sa.Column('env_variable', sa.String(length=64), nullable=False),
    sa.Column('value', sa.String(length=1024), nullable=False),
    sa.ForeignKeyConstraint(['server_id'], ['servers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('server_id', 'env_variable')
    )
    # The simple container table from 0005 is replaced by servers.
    op.drop_index(op.f('ix_containers_node_id'), table_name='containers')
    op.drop_table('containers')


def downgrade() -> None:
    """Downgrade schema."""
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
    op.drop_table('server_variables')
    op.drop_table('allocations')
    op.drop_table('servers')
    op.drop_table('egg_variables')
    op.drop_table('eggs')
    op.drop_table('nests')
