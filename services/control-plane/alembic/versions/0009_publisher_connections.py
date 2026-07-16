"""Create encrypted publisher OAuth connection storage.

Revision ID: 0009_publisher_connections
Revises: 0008_worker_context_lookup
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0009_publisher_connections"
down_revision = "0008_worker_context_lookup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "publisher_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_account_id", sa.String(256), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=False),
        sa.Column("scopes", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connected_by_subject", sa.String(512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("organization_id", "provider", "provider_account_id", name="uq_publisher_connection_account"),
    )
    op.create_index("ix_publisher_connections_org_provider", "publisher_connections", ["organization_id", "provider"])


def downgrade() -> None:
    op.drop_index("ix_publisher_connections_org_provider", table_name="publisher_connections")
    op.drop_table("publisher_connections")
