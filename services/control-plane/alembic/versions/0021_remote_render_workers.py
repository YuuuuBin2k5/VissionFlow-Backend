"""Durable outbound render worker queue."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0021_remote_render_workers"
down_revision = "0020_retrieval_hardening"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("render_workers", sa.Column("worker_id", sa.String(120), primary_key=True), sa.Column("worker_type", sa.String(48), nullable=False), sa.Column("status", sa.String(24), nullable=False), sa.Column("platform", sa.String(32), nullable=False), sa.Column("renderer_version", sa.String(80), nullable=False), sa.Column("ffmpeg_version", sa.String(160), nullable=False), sa.Column("capabilities", pg.JSONB(), nullable=False), sa.Column("max_concurrent_jobs", sa.Integer(), nullable=False), sa.Column("last_heartbeat_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.create_table("render_jobs", sa.Column("id", pg.UUID(as_uuid=True), primary_key=True), sa.Column("run_id", sa.String(128), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("priority", sa.Integer(), nullable=False), sa.Column("render_spec_version", sa.String(48), nullable=False), sa.Column("render_spec_json", pg.JSONB(), nullable=False), sa.Column("render_input_hash", sa.String(64), nullable=False), sa.Column("attempt", sa.Integer(), nullable=False), sa.Column("max_attempts", sa.Integer(), nullable=False), sa.Column("claimed_by_worker_id", sa.String(120), sa.ForeignKey("render_workers.worker_id")), sa.Column("lease_expires_at", sa.DateTime(timezone=True)), sa.Column("last_heartbeat_at", sa.DateTime(timezone=True)), sa.Column("completed_at", sa.DateTime(timezone=True)), sa.Column("failed_at", sa.DateTime(timezone=True)), sa.Column("error_code", sa.String(80)), sa.Column("error_message", sa.Text()), sa.Column("retryable", sa.Boolean(), nullable=False), sa.Column("output_artifact_ref", sa.String(1024)), sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.create_index("ix_render_jobs_claimable", "render_jobs", ["status", "priority", "created_at"])

def downgrade():
    op.drop_table("render_jobs")
    op.drop_table("render_workers")
