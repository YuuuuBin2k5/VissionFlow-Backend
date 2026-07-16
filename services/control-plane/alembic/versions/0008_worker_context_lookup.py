"""Add legacy_job_id mapping field to workflow_runs.

Revision ID: 0008_worker_context_lookup
Revises: 0007_add_context_fields
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_worker_context_lookup"
down_revision = "0007_add_context_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add legacy_job_id as a nullable string (VARCHAR(64)) to allow old/unmapped runs.
    op.add_column(
        "workflow_runs",
        sa.Column("legacy_job_id", sa.String(length=64), nullable=True),
    )
    # Enforce uniqueness globally so each MySQL job maps to at most one Postgres workflow run.
    op.create_unique_constraint(
        "uq_workflow_runs_legacy_job_id",
        "workflow_runs",
        ["legacy_job_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_workflow_runs_legacy_job_id",
        "workflow_runs",
        type_="unique",
    )
    op.drop_column("workflow_runs", "legacy_job_id")
