"""Create organization-scoped channel learning metrics.

Revision ID: 0022_channel_learning_metrics
Revises: 0021_remote_render_workers
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0022_channel_learning_metrics"
down_revision = "0021_remote_render_workers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_learning_metrics",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", pg.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_handle", sa.String(length=120), nullable=False),
        sa.Column("publication_attempt_id", pg.UUID(as_uuid=True), sa.ForeignKey("publication_attempts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("views_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("likes_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("shares_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("average_watch_time_sec", sa.Float(), nullable=False, server_default="0"),
        sa.Column("video_metadata_snapshot", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ai_winning_formula", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_channel_learnings_org_handle", "channel_learning_metrics", ["organization_id", "channel_handle"])


def downgrade() -> None:
    op.drop_index("ix_channel_learnings_org_handle", table_name="channel_learning_metrics")
    op.drop_table("channel_learning_metrics")
