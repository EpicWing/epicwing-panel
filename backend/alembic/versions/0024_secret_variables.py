"""Secret flag for egg variables."""

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "egg_variables",
        sa.Column("secret", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Existing eggs: mark the well known token variables as secret.
    op.execute(
        "UPDATE egg_variables SET secret = true "
        "WHERE env_variable IN ('DISCORD_TOKEN', 'GIT_ACCESS_TOKEN', 'BOT_TOKEN')"
    )


def downgrade() -> None:
    op.drop_column("egg_variables", "secret")
