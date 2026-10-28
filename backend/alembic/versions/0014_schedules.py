"""schedules and schedule tasks

Revision ID: 0014
Revises: 0013
"""
import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schedules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("server_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("cron_minute", sa.String(length=32), nullable=False),
        sa.Column("cron_hour", sa.String(length=32), nullable=False),
        sa.Column("cron_day_of_month", sa.String(length=32), nullable=False),
        sa.Column("cron_month", sa.String(length=32), nullable=False),
        sa.Column("cron_day_of_week", sa.String(length=32), nullable=False),
        sa.Column("only_when_online", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_schedules_server_id", "schedules", ["server_id"])
    op.create_index("ix_schedules_next_run_at", "schedules", ["next_run_at"])
    op.create_table(
        "schedule_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("schedule_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("payload", sa.String(length=1024), nullable=False),
        sa.Column("time_offset", sa.Integer(), server_default="0", nullable=False),
        sa.Column("continue_on_failure", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.ForeignKeyConstraint(["schedule_id"], ["schedules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("schedule_id", "sequence", name="uq_schedule_tasks_schedule_sequence"),
    )
    op.create_index("ix_schedule_tasks_schedule_id", "schedule_tasks", ["schedule_id"])


def downgrade() -> None:
    op.drop_table("schedule_tasks")
    op.drop_table("schedules")
