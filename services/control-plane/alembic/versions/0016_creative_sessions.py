"""Create creative sessions schema.

Revision ID: 0016_creative_sessions
Revises: 0015_provider_credential_vault
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0016_creative_sessions"
down_revision = "0015_provider_credential_vault"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Table: creative_sessions
    op.create_table(
        "creative_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("creation_spec", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("workflow_run_id", name="uq_creative_session_workflow_run"),
    )

    # 2. Table: creative_messages
    op.create_table(
        "creative_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("creative_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("actor IN ('user', 'assistant')", name="chk_creative_message_actor"),
    )

    # 3. Table: creative_proposals
    op.create_table(
        "creative_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("creative_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("creative_messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_proposal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("creative_proposals.id", ondelete="SET NULL"), nullable=True),
        sa.Column("state", sa.String(length=24), nullable=False, server_default="proposed"),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("brief", sa.Text(), nullable=False),
        sa.Column("script", sa.Text(), nullable=False),
        sa.Column("scenes", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("generation_manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.UniqueConstraint("session_id", "version", name="uq_creative_proposals_version"),
        sa.CheckConstraint("state IN ('proposed', 'accepted', 'superseded')", name="chk_creative_proposal_state"),
    )

    # 4. Table: creative_turns
    op.create_table(
        "creative_turns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("creative_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="generating"),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expected_revision", sa.Integer(), nullable=False),
        sa.Column("user_message_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("creative_messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("assistant_message_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("creative_messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("creative_proposals.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("generation_attempt_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("failure_code", sa.String(length=96), nullable=True),
        sa.UniqueConstraint("session_id", "idempotency_key", name="uq_creative_turns_session_idempotency"),
        sa.CheckConstraint("status IN ('generating', 'completed', 'failed')", name="chk_creative_turn_status"),
    )

    # 5. Table: creative_command_receipts
    op.create_table(
        "creative_command_receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("creative_sessions.id", ondelete="CASCADE"), nullable=True),
        sa.Column("operation_type", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("result_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("organization_id", "operation_type", "idempotency_key", name="uq_creative_command_receipts_key"),
    )

    # Indexes
    op.create_index("uq_active_generating_turn", "creative_turns", ["session_id"], unique=True, postgresql_where=sa.text("status = 'generating'"))
    op.create_index("uq_accepted_proposal_per_session", "creative_proposals", ["session_id"], unique=True, postgresql_where=sa.text("state = 'accepted'"))


def downgrade() -> None:
    op.drop_index("uq_accepted_proposal_per_session", table_name="creative_proposals")
    op.drop_index("uq_active_generating_turn", table_name="creative_turns")
    op.drop_table("creative_command_receipts")
    op.drop_table("creative_turns")
    op.drop_table("creative_proposals")
    op.drop_table("creative_messages")
    op.drop_table("creative_sessions")
