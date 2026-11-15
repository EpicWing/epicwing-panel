"""Drops the plugin table of databases that ran the old 0028."""

from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS server_packages")


def downgrade() -> None:
    pass
