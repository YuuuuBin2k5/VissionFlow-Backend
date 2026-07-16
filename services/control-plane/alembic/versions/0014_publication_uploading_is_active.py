"""Treat an externally-uploading publication attempt as active.

Revision ID: 0014_pub_upload_active
Revises: 0013_one_active_pub_attempt
"""
from alembic import op
import sqlalchemy as sa


revision = "0014_pub_upload_active"
down_revision = "0013_one_active_pub_attempt"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("uq_publication_attempts_one_active", table_name="publication_attempts")
    op.create_index(
        "uq_publication_attempts_one_active",
        "publication_attempts",
        ["workflow_run_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('requested', 'claimed', 'uploading')"),
    )


def downgrade() -> None:
    op.drop_index("uq_publication_attempts_one_active", table_name="publication_attempts")
    op.create_index(
        "uq_publication_attempts_one_active",
        "publication_attempts",
        ["workflow_run_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('requested', 'claimed')"),
    )
