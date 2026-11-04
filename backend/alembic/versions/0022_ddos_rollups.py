"""traffic guard: 5-minute rollups for a longer history"""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ddos_rollups",
        sa.Column("container", sa.String(128), primary_key=True),
        sa.Column("bucket", sa.BigInteger(), primary_key=True),
        sa.Column("rx", sa.BigInteger(), nullable=False),
        sa.Column("tx", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_ddos_rollups_bucket", "ddos_rollups", ["bucket"])


def downgrade() -> None:
    op.drop_index("ix_ddos_rollups_bucket", table_name="ddos_rollups")
    op.drop_table("ddos_rollups")
