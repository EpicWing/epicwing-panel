"""egg rules and config

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-09 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('eggs', sa.Column('config', sa.Text(), server_default='{}', nullable=False))
    op.add_column('egg_variables', sa.Column('user_viewable', sa.Boolean(), server_default=sa.true(), nullable=False))
    op.add_column('egg_variables', sa.Column('rules', sa.String(length=512), server_default='nullable|string', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('egg_variables', 'rules')
    op.drop_column('egg_variables', 'user_viewable')
    op.drop_column('eggs', 'config')
