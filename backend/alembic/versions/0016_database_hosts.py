"""database hosts and server databases

Revision ID: 0016
Revises: 0015
"""
import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "database_hosts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("admin_user", sa.String(length=64), nullable=False),
        sa.Column("admin_password", sa.Text(), nullable=False),
        sa.Column("max_databases", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "server_databases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("server_id", sa.Uuid(), nullable=False),
        sa.Column("host_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("username", sa.String(length=32), nullable=False),
        sa.Column("remote", sa.String(length=255), nullable=False),
        sa.Column("password", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["host_id"], ["database_hosts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("host_id", "name", name="uq_server_databases_host_name"),
        sa.UniqueConstraint("host_id", "username", name="uq_server_databases_host_user"),
    )
    op.create_index("ix_server_databases_server_id", "server_databases", ["server_id"])
    op.create_index("ix_server_databases_host_id", "server_databases", ["host_id"])


def downgrade() -> None:
    op.drop_index("ix_server_databases_host_id", table_name="server_databases")
    op.drop_index("ix_server_databases_server_id", table_name="server_databases")
    op.drop_table("server_databases")
    op.drop_table("database_hosts")
