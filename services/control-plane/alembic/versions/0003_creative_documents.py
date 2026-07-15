"""Add versioned creative documents and scene entities.

Revision ID: 0003_creative_documents
Revises: 0002_local_auth_foundation
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_creative_documents"
down_revision = "0002_local_auth_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    op.create_table(
        "creative_documents",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("workflow_run_id", uuid_type, sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active_version_id", uuid_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "creative_document_versions",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("creative_document_id", uuid_type, sa.ForeignKey("creative_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False, server_default="draft"),
        sa.Column("script", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False, server_default="operator"),
        sa.Column("created_by_subject", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("creative_document_id", "version", name="uq_creative_document_version"),
    )
    op.create_table(
        "creative_scenes",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("creative_document_version_id", uuid_type, sa.ForeignKey("creative_document_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("narration", sa.Text(), nullable=False),
        sa.Column("visual_prompt", sa.Text(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("transition", sa.String(length=48), nullable=False, server_default="cut"),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("creative_document_version_id", "position", name="uq_creative_scene_position"),
    )


def downgrade() -> None:
    op.drop_table("creative_scenes")
    op.drop_table("creative_document_versions")
    op.drop_table("creative_documents")
