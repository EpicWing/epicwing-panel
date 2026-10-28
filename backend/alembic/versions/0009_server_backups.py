"""server backups

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-15 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0009'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('servers', sa.Column('backup_limit', sa.Integer(), server_default='0', nullable=False))
    op.create_table('server_backups',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('server_id', sa.Uuid(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=True),
    sa.Column('is_locked', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('ignored', sa.Text(), server_default='', nullable=False),
    sa.Column('error', sa.String(length=1024), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['server_id'], ['servers.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_server_backups_server_id'), 'server_backups', ['server_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_server_backups_server_id'), table_name='server_backups')
    op.drop_table('server_backups')
    op.drop_column('servers', 'backup_limit')
