"""Add local VisionFlow authentication aggregates.

Revision ID: 0002_local_auth_foundation
Revises: 0001_initial_visionflow_v1
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0002_local_auth_foundation"
down_revision = "0001_initial_visionflow_v1"
branch_labels = None
depends_on = None


uuid_type = postgresql.UUID(as_uuid=True)
json_type = postgresql.JSONB(astext_type=sa.Text())


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    ]


def upgrade() -> None:
    op.create_table(
        "auth_users",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("email", sa.String(length=320), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        *_timestamps(),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("auth_user_id", uuid_type, sa.ForeignKey("auth_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(length=96), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_auth_sessions_user_active", "auth_sessions", ["auth_user_id", "expires_at"])
    op.create_table(
        "auth_refresh_tokens",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("session_id", uuid_type, sa.ForeignKey("auth_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_id", uuid_type, sa.ForeignKey("auth_refresh_tokens.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_auth_refresh_tokens_session_expiry", "auth_refresh_tokens", ["session_id", "expires_at"])
    op.create_table(
        "auth_audit_events",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("auth_user_id", uuid_type, sa.ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("metadata_json", json_type, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_auth_audit_events_user_created", "auth_audit_events", ["auth_user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_auth_audit_events_user_created", table_name="auth_audit_events")
    op.drop_table("auth_audit_events")
    op.drop_index("ix_auth_refresh_tokens_session_expiry", table_name="auth_refresh_tokens")
    op.drop_table("auth_refresh_tokens")
    op.drop_index("ix_auth_sessions_user_active", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("auth_users")
