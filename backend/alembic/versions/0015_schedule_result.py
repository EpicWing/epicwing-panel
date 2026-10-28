"""schedule last result

Revision ID: 0015
Revises: 0014
"""
import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("schedules", sa.Column("last_result", sa.String(length=16), nullable=True))
    op.add_column("schedules", sa.Column("last_detail", sa.String(length=300), nullable=True))


def downgrade() -> None:
    op.drop_column("schedules", "last_detail")
    op.drop_column("schedules", "last_result")
