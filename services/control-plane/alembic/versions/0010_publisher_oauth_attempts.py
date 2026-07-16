"""Create one-time publisher OAuth state attempts.

Revision ID: 0010_publisher_oauth_attempts
Revises: 0009_publisher_connections
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0010_publisher_oauth_attempts"
down_revision = "0009_publisher_connections"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table("publisher_oauth_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("state_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("requested_by_subject", sa.String(512), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_publisher_oauth_attempts_expiry", "publisher_oauth_attempts", ["expires_at"])

def downgrade() -> None:
    op.drop_index("ix_publisher_oauth_attempts_expiry", table_name="publisher_oauth_attempts")
    op.drop_table("publisher_oauth_attempts")
