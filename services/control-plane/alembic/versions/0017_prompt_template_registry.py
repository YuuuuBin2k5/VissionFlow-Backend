"""Create prompt_templates and prompt_versions tables and seed baseline prompts.

Revision ID: 0017_prompt_template_registry
Revises: 0016_creative_sessions
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0017_prompt_template_registry"
down_revision = "0016_creative_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    # 1. Create prompt_templates table if not exists
    if "prompt_templates" not in tables:
        op.create_table(
            "prompt_templates",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("prompt_key", sa.String(length=100), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("production_version", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("organization_id", "prompt_key", name="uq_prompt_template_key"),
        )

    # 2. Create prompt_versions table if not exists
    if "prompt_versions" not in tables:
        op.create_table(
            "prompt_versions",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("prompt_template_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("prompt_templates.id", ondelete="CASCADE"), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("change_note", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("prompt_template_id", "version", name="uq_prompt_version"),
        )

    # 3. Create system-wide seed entries for each existing organization.
    #    Uses a DO block so the INSERT is idempotent on re-run.
    op.execute(sa.text("""
DO $$
DECLARE
    org_id UUID;
    planner_tmpl_id UUID;
    director_tmpl_id UUID;
BEGIN
    FOR org_id IN SELECT id FROM organizations LOOP

        -- ── short_video_scene_planner ────────────────────────────────────────
        INSERT INTO prompt_templates (id, organization_id, prompt_key, name, description, production_version)
        VALUES (
            gen_random_uuid(), org_id,
            'short_video_scene_planner',
            'Short video scene planner',
            'Acts as the scene planning director: breaks down the creative brief and chat context into a structured list of scenes for the short-video renderer.',
            1
        )
        ON CONFLICT (organization_id, prompt_key) DO NOTHING;

        SELECT id INTO planner_tmpl_id
        FROM prompt_templates
        WHERE organization_id = org_id AND prompt_key = 'short_video_scene_planner';

        INSERT INTO prompt_versions (id, prompt_template_id, version, content, config, change_note)
        VALUES (
            gen_random_uuid(), planner_tmpl_id, 1,
            'Bạn là Đạo diễn Phân cảnh của VisionFlow AI. Nhiệm vụ của bạn là đọc hiểu yêu cầu sáng tạo từ người dùng và lịch sử hội thoại, sau đó xây dựng một kịch bản phân cảnh chi tiết cho video ngắn dọc (9:16).

[QUY TẮC BẮT BUỘC]:
1. Mỗi phân cảnh phải có đủ: narration (lời thoại), visual_prompt (mô tả hình ảnh tiếng Anh), duration_seconds (3-20 giây), transition (cut/fade/dissolve/zoom_in/zoom_out), caption (phụ đề hiển thị).
2. Tổng thời lượng các cảnh phải xấp xỉ thời lượng yêu cầu trong creation_spec.
3. Lời thoại (narration) viết bằng ngôn ngữ được chỉ định trong creation_spec, ngắn gọn, thu hút.
4. visual_prompt luôn viết bằng tiếng Anh, mô tả chi tiết: nhân vật, hành động, góc máy, ánh sáng, màu sắc, phong cách.
5. Số lượng phân cảnh từ 3 đến 20 cảnh.
6. Phân bổ thời lượng hợp lý, cảnh mở đầu và kết thúc thường ngắn hơn cảnh giữa.
7. Tone và phong cách phải nhất quán với visual_preset và brief đã cung cấp.',
            '{"model": "gemini-2.5-flash", "temperature": 0.7, "response_mime_type": "application/json"}'::jsonb,
            'Initial baseline prompt seeded by migration 0017.'
        )
        ON CONFLICT (prompt_template_id, version) DO NOTHING;

        -- ── short_video_visual_art_director ──────────────────────────────────
        INSERT INTO prompt_templates (id, organization_id, prompt_key, name, description, production_version)
        VALUES (
            gen_random_uuid(), org_id,
            'short_video_visual_art_director',
            'Short video visual art director',
            'Acts as the visual art director: expands each scene narration into a rich, cinematic English media-search and render prompt.',
            1
        )
        ON CONFLICT (organization_id, prompt_key) DO NOTHING;

        SELECT id INTO director_tmpl_id
        FROM prompt_templates
        WHERE organization_id = org_id AND prompt_key = 'short_video_visual_art_director';

        INSERT INTO prompt_versions (id, prompt_template_id, version, content, config, change_note)
        VALUES (
            gen_random_uuid(), director_tmpl_id, 1,
            'You are the Visual Art Director for VisionFlow AI. Your role is to transform each scene narration and the overall creative brief into a highly detailed, cinematic English visual prompt suitable for AI image/video generation and stock media search.

[MANDATORY RULES]:
1. Always write visual_prompt in English regardless of the video language.
2. Include: subject description, action, camera angle (close-up/wide/medium shot), lighting style, color palette, mood, and the visual_preset theme from the creation spec.
3. Keep the composition optimized for vertical 9:16 short-form video.
4. Ensure visual consistency across all scenes (same characters, color grading, art style).
5. Append technical tags at the end: cinematic lighting, 4K, vertical composition, professional quality.
6. The prompt must be self-contained — do not reference previous scenes by number.
7. Adapt the style to match the format_profile and visual_preset supplied in the creation spec.',
            '{"model": "gemini-2.5-flash", "temperature": 0.4, "response_mime_type": "application/json"}'::jsonb,
            'Initial baseline prompt seeded by migration 0017.'
        )
        ON CONFLICT (prompt_template_id, version) DO NOTHING;

    END LOOP;
END $$;
"""))


def downgrade() -> None:
    op.drop_table("prompt_versions")
    op.drop_table("prompt_templates")
