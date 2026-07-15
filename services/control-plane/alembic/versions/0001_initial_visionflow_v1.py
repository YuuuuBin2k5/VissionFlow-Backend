"""Create initial PostgreSQL-only VisionFlow V1 aggregates.

Revision ID: 0001_initial_visionflow_v1
Revises:
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_initial_visionflow_v1"
down_revision = None
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
        "organizations",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("slug", sa.String(length=80), nullable=False, unique=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "users",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("identity_subject", sa.String(length=512), nullable=False, unique=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("display_name", sa.String(length=160), nullable=True),
        *_timestamps(),
    )
    op.create_table(
        "organization_memberships",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_organization_membership"),
    )
    op.create_index("ix_organization_memberships_user", "organization_memberships", ["user_id"])
    op.create_table(
        "video_projects",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("brief", sa.Text(), nullable=False),
        sa.Column("format_profile", sa.String(length=64), nullable=False, server_default="short_vertical"),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Asia/Bangkok"),
        *_timestamps(),
    )
    op.create_index("ix_video_projects_organization_created", "video_projects", ["organization_id", "created_at"])
    op.create_table(
        "workflow_runs",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("project_id", uuid_type, sa.ForeignKey("video_projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False, unique=True),
        sa.Column("prompt_manifest", json_type, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("input_payload", json_type, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("failure_code", sa.String(length=96), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_workflow_runs_project_created", "workflow_runs", ["project_id", "created_at"])
    op.create_index("ix_workflow_runs_state_created", "workflow_runs", ["state", "created_at"])
    op.create_table(
        "workflow_steps",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("workflow_run_id", uuid_type, sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_key", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_payload", json_type, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("output_payload", json_type, nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("workflow_run_id", "step_key", name="uq_workflow_step_key"),
    )
    op.create_index("ix_workflow_steps_run_state", "workflow_steps", ["workflow_run_id", "state"])
    op.create_table(
        "prompt_templates",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("prompt_key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("production_version", sa.Integer(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("organization_id", "prompt_key", name="uq_prompt_template_key"),
    )
    op.create_table(
        "prompt_versions",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("prompt_template_id", uuid_type, sa.ForeignKey("prompt_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("config", json_type, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("change_note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("prompt_template_id", "version", name="uq_prompt_version"),
    )
    op.create_table(
        "prompt_audit_events",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("prompt_template_id", uuid_type, sa.ForeignKey("prompt_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("actor_subject", sa.String(length=512), nullable=False),
        sa.Column("payload", json_type, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_prompt_audit_events_template_created",
        "prompt_audit_events",
        ["prompt_template_id", "created_at"],
    )
    op.create_table(
        "media_assets",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("organization_id", uuid_type, sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("workflow_run_id", uuid_type, sa.ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("object_key", sa.String(length=1024), nullable=False, unique=True),
        sa.Column("media_kind", sa.String(length=48), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", json_type, nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_timestamps(),
    )
    op.create_index("ix_media_assets_run_kind", "media_assets", ["workflow_run_id", "media_kind"])
    op.create_table(
        "publish_approvals",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("workflow_run_id", uuid_type, sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("export_asset_id", uuid_type, sa.ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("decision", sa.String(length=24), nullable=False),
        sa.Column("reviewer_subject", sa.String(length=255), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        *_timestamps(),
    )
    op.create_table(
        "outbox_events",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("aggregate_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", uuid_type, nullable=False),
        sa.Column("event_type", sa.String(length=160), nullable=False),
        sa.Column("payload", json_type, nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_outbox_events_pending",
        "outbox_events",
        ["created_at"],
        postgresql_where=sa.text("published_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_events_pending", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_table("publish_approvals")
    op.drop_index("ix_media_assets_run_kind", table_name="media_assets")
    op.drop_table("media_assets")
    op.drop_index("ix_prompt_audit_events_template_created", table_name="prompt_audit_events")
    op.drop_table("prompt_audit_events")
    op.drop_table("prompt_versions")
    op.drop_table("prompt_templates")
    op.drop_index("ix_workflow_steps_run_state", table_name="workflow_steps")
    op.drop_table("workflow_steps")
    op.drop_index("ix_workflow_runs_state_created", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_project_created", table_name="workflow_runs")
    op.drop_table("workflow_runs")
    op.drop_index("ix_video_projects_organization_created", table_name="video_projects")
    op.drop_table("video_projects")
    op.drop_index("ix_organization_memberships_user", table_name="organization_memberships")
    op.drop_table("organization_memberships")
    op.drop_table("users")
    op.drop_table("organizations")
