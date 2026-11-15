"""Wider server variable values, because encrypted values are longer than plain text."""

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "server_variables",
        "value",
        existing_type=sa.String(1024),
        type_=sa.String(8192),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "server_variables",
        "value",
        existing_type=sa.String(8192),
        type_=sa.String(1024),
        existing_nullable=False,
    )
