"""Add foreign keys and indexes to CommandReceipts and WorkflowAuditEvents.

Revision ID: 0006_command_receipts_hardened
Revises: 0005_command_receipts_and_audit
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006_command_receipts_hardened"
down_revision = "0005_command_receipts_and_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add foreign keys to command_receipts
    op.create_foreign_key(
        "fk_command_receipts_org",
        "command_receipts",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_command_receipts_workflow_run",
        "command_receipts",
        "workflow_runs",
        ["workflow_run_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 2. Add foreign key to workflow_audit_events
    op.create_foreign_key(
        "fk_workflow_audit_events_target_version",
        "workflow_audit_events",
        "creative_document_versions",
        ["target_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 3. Add composite indexes
    op.create_index(
        "ix_command_receipts_org_workflow",
        "command_receipts",
        ["organization_id", "workflow_run_id"],
    )
    op.create_index(
        "ix_workflow_audit_events_org_workflow_time",
        "workflow_audit_events",
        ["organization_id", "workflow_run_id", "created_at"],
    )


def downgrade() -> None:
    # 1. Drop composite indexes
    op.drop_index("ix_workflow_audit_events_org_workflow_time", table_name="workflow_audit_events")
    op.drop_index("ix_command_receipts_org_workflow", table_name="command_receipts")

    # 2. Drop foreign keys from workflow_audit_events
    op.drop_constraint("fk_workflow_audit_events_target_version", "workflow_audit_events", type_="foreignkey")

    # 3. Drop foreign keys from command_receipts
    op.drop_constraint("fk_command_receipts_workflow_run", "command_receipts", type_="foreignkey")
    op.drop_constraint("fk_command_receipts_org", "command_receipts", type_="foreignkey")
