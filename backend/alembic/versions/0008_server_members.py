"""server members and permissions

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-15 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('server_members',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('server_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['server_id'], ['servers.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('server_id', 'user_id', name='uq_server_members_server_user')
    )
    op.create_index(op.f('ix_server_members_server_id'), 'server_members', ['server_id'], unique=False)
    op.create_index(op.f('ix_server_members_user_id'), 'server_members', ['user_id'], unique=False)
    op.create_table('server_member_permissions',
    sa.Column('member_id', sa.Uuid(), nullable=False),
    sa.Column('permission', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['member_id'], ['server_members.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('member_id', 'permission')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('server_member_permissions')
    op.drop_index(op.f('ix_server_members_user_id'), table_name='server_members')
    op.drop_index(op.f('ix_server_members_server_id'), table_name='server_members')
    op.drop_table('server_members')
