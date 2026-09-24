"""Add durable automation batches and jobs.

Revision ID: 0023_automation_batches
Revises: 0022_channel_learning_metrics
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0023_automation_batches"
down_revision = "0022_channel_learning_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "automation_batches",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", pg.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="QUEUED"),
        sa.Column("approval_policy", sa.String(length=32), nullable=False, server_default="REVIEW_REQUIRED"),
        sa.Column("channel_profile_id", sa.String(length=160), nullable=True),
        sa.Column("settings", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("requested_by_subject", sa.String(length=512), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_automation_batches_org_idempotency"),
    )
    op.create_index("ix_automation_batches_org_created", "automation_batches", ["organization_id", "created_at"])
    op.create_table(
        "automation_jobs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("batch_id", pg.UUID(as_uuid=True), sa.ForeignKey("automation_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("state", sa.String(length=40), nullable=False, server_default="QUEUED"),
        sa.Column("source_payload", pg.JSONB(), nullable=False),
        sa.Column("production_run_id", sa.String(length=128), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("error_code", sa.String(length=96), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("batch_id", "position", name="uq_automation_jobs_batch_position"),
    )
    op.create_index("ix_automation_jobs_batch_state", "automation_jobs", ["batch_id", "state"])
    op.create_index("ix_automation_jobs_run_id", "automation_jobs", ["production_run_id"])


def downgrade() -> None:
    op.drop_index("ix_automation_jobs_run_id", table_name="automation_jobs")
    op.drop_index("ix_automation_jobs_batch_state", table_name="automation_jobs")
    op.drop_table("automation_jobs")
    op.drop_index("ix_automation_batches_org_created", table_name="automation_batches")
    op.drop_table("automation_batches")
