"""Enforce one active retry publication attempt per workflow.

Revision ID: 0013_one_active_pub_attempt
Revises: 0012_pub_attempt_lease
"""

from alembic import op
import sqlalchemy as sa


revision = "0013_one_active_pub_attempt"
down_revision = "0012_pub_attempt_lease"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_publication_attempts_one_active",
        "publication_attempts",
        ["workflow_run_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('requested', 'claimed')"),
    )


def downgrade() -> None:
    op.drop_index("uq_publication_attempts_one_active", table_name="publication_attempts")
