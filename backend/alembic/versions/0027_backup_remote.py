"""Backups in object storage."""

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("server_backups", sa.Column("remote_state", sa.String(16)))
    op.add_column("server_backups", sa.Column("remote_key", sa.String(512)))
    op.add_column("server_backups", sa.Column("remote_upload_id", sa.String(1024)))
    op.add_column("server_backups", sa.Column("remote_error", sa.String(1024)))
    op.add_column(
        "server_backups",
        sa.Column("local", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    for column in ("local", "remote_error", "remote_upload_id", "remote_key", "remote_state"):
        op.drop_column("server_backups", column)
