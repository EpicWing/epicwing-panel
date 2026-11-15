"""Plugins and mods from the marketplace, per server."""

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "server_packages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "server_id",
            sa.Uuid(),
            sa.ForeignKey("servers.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("package_id", sa.String(63), nullable=False),
        sa.Column("registry", sa.String(201), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("version", sa.String(48), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("path", sa.String(1024), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column(
            "installed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("server_id", "package_id", name="uq_server_packages_server_package"),
    )


def downgrade() -> None:
    op.drop_table("server_packages")
