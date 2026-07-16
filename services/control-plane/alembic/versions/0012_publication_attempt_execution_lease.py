"""Make retry publication execution lease based and auditable.

Revision ID: 0012_pub_attempt_lease
Revises: 0011_publication_attempts
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_pub_attempt_lease"
down_revision = "0011_publication_attempts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("publication_attempts", sa.Column("lease_token", sa.String(length=64), nullable=True))
    op.add_column("publication_attempts", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("publication_attempts", sa.Column("external_video_id", sa.String(length=255), nullable=True))
    op.add_column("publication_attempts", sa.Column("external_url", sa.String(length=2048), nullable=True))
    op.create_index("ix_publication_attempts_lease_expires_at", "publication_attempts", ["lease_expires_at"])


def downgrade() -> None:
    op.drop_index("ix_publication_attempts_lease_expires_at", table_name="publication_attempts")
    op.drop_column("publication_attempts", "external_url")
    op.drop_column("publication_attempts", "external_video_id")
    op.drop_column("publication_attempts", "lease_expires_at")
    op.drop_column("publication_attempts", "lease_token")
