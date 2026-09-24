"""Add AI thumbnails and scheduling fields to automation jobs.

Revision ID: 0024_thumbnails_scheduling
Revises: 0023_automation_batches
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0024_thumbnails_scheduling"
down_revision = "0023_automation_batches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "automation_jobs",
        sa.Column("thumbnail_urls", pg.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column(
        "automation_jobs",
        sa.Column("selected_thumbnail_url", sa.String(length=1024), nullable=True),
    )
    op.add_column(
        "automation_jobs",
        sa.Column("scheduled_publish_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "automation_jobs",
        sa.Column("schedule_platform", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "automation_jobs",
        sa.Column("auto_publish_policy", sa.String(length=32), nullable=False, server_default="MANUAL"),
    )


def downgrade() -> None:
    op.drop_column("automation_jobs", "auto_publish_policy")
    op.drop_column("automation_jobs", "schedule_platform")
    op.drop_column("automation_jobs", "scheduled_publish_at")
    op.drop_column("automation_jobs", "selected_thumbnail_url")
    op.drop_column("automation_jobs", "thumbnail_urls")
