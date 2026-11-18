"""A name per user that is shown instead of the email address."""

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("display_name", sa.String(48), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "display_name")
