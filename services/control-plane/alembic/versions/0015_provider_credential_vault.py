"""Create encrypted provider credential vault.

Revision ID: 0015_provider_credential_vault
Revises: 0014_pub_upload_active
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0015_provider_credential_vault"
down_revision = "0014_pub_upload_active"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("secret_ciphertext", sa.Text(), nullable=False),
        sa.Column("secret_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="active"),
        sa.Column("capabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by_subject", sa.String(length=512), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_code", sa.String(length=96), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("organization_id", "provider", "label", name="uq_provider_credential_label"),
    )
    op.create_index("ix_provider_credentials_resolution", "provider_credentials", ["organization_id", "provider", "status", "priority"])
    op.create_table(
        "provider_credential_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("credential_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("provider_credentials.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_subject", sa.String(length=512), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_provider_credential_audit_org_time", "provider_credential_audit_events", ["organization_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_provider_credential_audit_org_time", table_name="provider_credential_audit_events")
    op.drop_table("provider_credential_audit_events")
    op.drop_index("ix_provider_credentials_resolution", table_name="provider_credentials")
    op.drop_table("provider_credentials")
