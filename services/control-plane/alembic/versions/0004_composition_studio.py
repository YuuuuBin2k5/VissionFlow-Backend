"""Add versioned Composition Studio timeline entities.

Revision ID: 0004_composition_studio
Revises: 0003_creative_documents
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004_composition_studio"
down_revision = "0003_creative_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    op.create_table("composition_documents", sa.Column("id", uuid_type, primary_key=True), sa.Column("workflow_run_id", uuid_type, sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False, unique=True), sa.Column("revision", sa.Integer(), nullable=False, server_default="0"), sa.Column("active_version_id", uuid_type), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))
    op.create_table("composition_versions", sa.Column("id", uuid_type, primary_key=True), sa.Column("composition_document_id", uuid_type, sa.ForeignKey("composition_documents.id", ondelete="CASCADE"), nullable=False), sa.Column("revision", sa.Integer(), nullable=False), sa.Column("state", sa.String(24), nullable=False, server_default="draft"), sa.Column("aspect_ratio", sa.String(24), nullable=False, server_default="9:16"), sa.Column("canvas_config", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("created_by_subject", sa.String(512), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")), sa.UniqueConstraint("composition_document_id", "revision", name="uq_composition_revision"))
    op.create_table("composition_tracks", sa.Column("id", uuid_type, primary_key=True), sa.Column("composition_version_id", uuid_type, sa.ForeignKey("composition_versions.id", ondelete="CASCADE"), nullable=False), sa.Column("position", sa.Integer(), nullable=False), sa.Column("track_type", sa.String(32), nullable=False), sa.Column("name", sa.String(120), nullable=False), sa.Column("muted", sa.Boolean(), nullable=False, server_default=sa.text("false")), sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.text("false")), sa.UniqueConstraint("composition_version_id", "position", name="uq_composition_track_position"))
    op.create_table("composition_clips", sa.Column("id", uuid_type, primary_key=True), sa.Column("composition_track_id", uuid_type, sa.ForeignKey("composition_tracks.id", ondelete="CASCADE"), nullable=False), sa.Column("position", sa.Integer(), nullable=False), sa.Column("source_type", sa.String(32), nullable=False), sa.Column("source_ref", sa.String(1024), nullable=False), sa.Column("timeline_start_ms", sa.Integer(), nullable=False), sa.Column("duration_ms", sa.Integer(), nullable=False), sa.Column("trim_in_ms", sa.Integer(), nullable=False, server_default="0"), sa.Column("transform", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")), sa.UniqueConstraint("composition_track_id", "position", name="uq_composition_clip_position"))
    op.create_table("composition_effect_instances", sa.Column("id", uuid_type, primary_key=True), sa.Column("composition_clip_id", uuid_type, sa.ForeignKey("composition_clips.id", ondelete="CASCADE"), nullable=False), sa.Column("position", sa.Integer(), nullable=False), sa.Column("effect_key", sa.String(120), nullable=False), sa.Column("config", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")), sa.UniqueConstraint("composition_clip_id", "position", name="uq_composition_effect_position"))
    op.create_table("composition_keyframes", sa.Column("id", uuid_type, primary_key=True), sa.Column("composition_clip_id", uuid_type, sa.ForeignKey("composition_clips.id", ondelete="CASCADE"), nullable=False), sa.Column("property_key", sa.String(96), nullable=False), sa.Column("time_ms", sa.Integer(), nullable=False), sa.Column("value", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("easing", sa.String(48), nullable=False, server_default="linear"), sa.UniqueConstraint("composition_clip_id", "property_key", "time_ms", name="uq_composition_keyframe"))


def downgrade() -> None:
    op.drop_table("composition_keyframes"); op.drop_table("composition_effect_instances"); op.drop_table("composition_clips"); op.drop_table("composition_tracks"); op.drop_table("composition_versions"); op.drop_table("composition_documents")
