"""nodes: optional limits for memory and storage that servers may use together"""

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL heißt unbegrenzt
    op.add_column("nodes", sa.Column("ram_limit_mb", sa.Integer(), nullable=True))
    op.add_column("nodes", sa.Column("disk_limit_mb", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("nodes", "disk_limit_mb")
    op.drop_column("nodes", "ram_limit_mb")
