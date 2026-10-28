"""ddos samples

Revision ID: 0019
Revises: 0018
"""
import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ddos_samples",
        sa.Column("container", sa.String(length=128), nullable=False),
        sa.Column("bucket", sa.BigInteger(), nullable=False),
        sa.Column("rx", sa.BigInteger(), nullable=False),
        sa.Column("tx", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("container", "bucket"),
    )
    op.create_index("ix_ddos_samples_bucket", "ddos_samples", ["bucket"])


def downgrade() -> None:
    op.drop_index("ix_ddos_samples_bucket", table_name="ddos_samples")
    op.drop_table("ddos_samples")
