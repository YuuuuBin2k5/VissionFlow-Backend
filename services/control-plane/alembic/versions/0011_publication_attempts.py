"""publication retry attempts

Revision ID: 0011_publication_attempts
Revises: 0010_publisher_oauth_attempts
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0011_publication_attempts"
down_revision = "0010_publisher_oauth_attempts"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table("publication_attempts", sa.Column("id", UUID(as_uuid=True), primary_key=True), sa.Column("workflow_run_id", UUID(as_uuid=True), sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False), sa.Column("publisher_connection_id", UUID(as_uuid=True), sa.ForeignKey("publisher_connections.id", ondelete="RESTRICT"), nullable=False), sa.Column("attempt_number", sa.Integer(), nullable=False), sa.Column("state", sa.String(32), nullable=False, server_default="requested"), sa.Column("requested_by_subject", sa.String(512), nullable=False), sa.Column("failure_code", sa.String(96), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.UniqueConstraint("workflow_run_id", "attempt_number", name="uq_publication_attempt_number"))

def downgrade() -> None:
    op.drop_table("publication_attempts")
