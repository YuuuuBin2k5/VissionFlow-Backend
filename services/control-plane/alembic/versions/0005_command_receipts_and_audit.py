"""Add CommandReceipts and WorkflowAuditEvents tables.

Revision ID: 0005_command_receipts_and_audit
Revises: 0004_composition_studio
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0005_command_receipts_and_audit"
down_revision = "0004_composition_studio"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)

    # 1. create command_receipts table
    op.create_table(
        "command_receipts",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("organization_id", uuid_type, nullable=False),
        sa.Column("operation_type", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("workflow_run_id", uuid_type, nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("result_payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # 2. create workflow_audit_events table
    op.create_table(
        "workflow_audit_events",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workflow_run_id", uuid_type, sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("actor_subject", sa.String(512), nullable=False),
        sa.Column("target_version_id", uuid_type, nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("workflow_audit_events")
    op.drop_table("command_receipts")
