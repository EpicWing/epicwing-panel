"""auto restart

Revision ID: 0020
Revises: 0019
"""
import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "servers",
        sa.Column("auto_restart", sa.String(length=8), nullable=False, server_default="always"),
    )
    op.add_column(
        "servers",
        sa.Column("auto_restart_delay", sa.Integer(), nullable=False, server_default="30"),
    )
    op.add_column(
        "servers",
        sa.Column("auto_restart_max_failures", sa.Integer(), nullable=False, server_default="5"),
    )
    op.add_column(
        "servers",
        sa.Column("restart_failures", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "servers", sa.Column("restart_due_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "servers", sa.Column("last_auto_start_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    for column in (
        "last_auto_start_at",
        "restart_due_at",
        "restart_failures",
        "auto_restart_max_failures",
        "auto_restart_delay",
        "auto_restart",
    ):
        op.drop_column("servers", column)
