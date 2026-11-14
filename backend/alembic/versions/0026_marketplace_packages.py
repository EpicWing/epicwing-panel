"""Installed marketplace packages."""

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "marketplace_packages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("package_id", sa.String(63), nullable=False, unique=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("version", sa.String(48), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("repository", sa.String(201), nullable=False),
        sa.Column("commit", sa.String(40), nullable=False),
        sa.Column("egg_id", sa.Uuid(), sa.ForeignKey("eggs.id", ondelete="SET NULL")),
        sa.Column("installed_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "installed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("marketplace_packages")
