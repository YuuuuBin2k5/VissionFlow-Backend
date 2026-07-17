"""
One-shot script: seeds prompt_templates + prompt_versions for ALL existing
organizations using DATABASE_URL (pooled, no MIGRATION_DATABASE_URL needed).

Usage (run on Render Shell or locally):
    python scripts/seed_prompt_baselines.py

Safe to re-run: uses INSERT ... ON CONFLICT DO NOTHING.
"""
from __future__ import annotations

import os
import sys
import uuid
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── allow running from repo root ──────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine, text

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    sys.exit("ERROR: DATABASE_URL env var is not set.")

# Normalise scheme for psycopg3
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len("postgresql://"):]

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

PLANNER_CONTENT = """\
Bạn là Đạo diễn Phân cảnh của VisionFlow AI. Nhiệm vụ của bạn là đọc hiểu yêu cầu sáng tạo từ người dùng và lịch sử hội thoại, sau đó xây dựng một kịch bản phân cảnh chi tiết cho video ngắn dọc (9:16).

[QUY TẮC BẮT BUỘC]:
1. Mỗi phân cảnh phải có đủ: narration (lời thoại), visual_prompt (mô tả hình ảnh tiếng Anh), duration_seconds (3-20 giây), transition (cut/fade/dissolve/zoom_in/zoom_out), caption (phụ đề hiển thị).
2. Tổng thời lượng các cảnh phải xấp xỉ thời lượng yêu cầu trong creation_spec.
3. Lời thoại (narration) viết bằng ngôn ngữ được chỉ định trong creation_spec, ngắn gọn, thu hút.
4. visual_prompt luôn viết bằng tiếng Anh, mô tả chi tiết: nhân vật, hành động, góc máy, ánh sáng, màu sắc, phong cách.
5. Số lượng phân cảnh từ 3 đến 20 cảnh.
6. Phân bổ thời lượng hợp lý, cảnh mở đầu và kết thúc thường ngắn hơn cảnh giữa.
7. Tone và phong cách phải nhất quán với visual_preset và brief đã cung cấp.\
"""

DIRECTOR_CONTENT = """\
You are the Visual Art Director for VisionFlow AI. Your role is to transform each scene narration and the overall creative brief into a highly detailed, cinematic English visual prompt suitable for AI image/video generation and stock media search.

[MANDATORY RULES]:
1. Always write visual_prompt in English regardless of the video language.
2. Include: subject description, action, camera angle (close-up/wide/medium shot), lighting style, color palette, mood, and the visual_preset theme from the creation spec.
3. Keep the composition optimized for vertical 9:16 short-form video.
4. Ensure visual consistency across all scenes (same characters, color grading, art style).
5. Append technical tags at the end: cinematic lighting, 4K, vertical composition, professional quality.
6. The prompt must be self-contained — do not reference previous scenes by number.
7. Adapt the style to match the format_profile and visual_preset supplied in the creation spec.\
"""

PROMPTS = [
    {
        "key": "short_video_scene_planner",
        "name": "Short video scene planner",
        "description": "Acts as the scene planning director for short-video renderer.",
        "content": PLANNER_CONTENT,
        "config": '{"model":"gemini-2.5-flash","temperature":0.7,"response_mime_type":"application/json"}',
    },
    {
        "key": "short_video_visual_art_director",
        "name": "Short video visual art director",
        "description": "Acts as the visual art director for media search and render prompts.",
        "content": DIRECTOR_CONTENT,
        "config": '{"model":"gemini-2.5-flash","temperature":0.4,"response_mime_type":"application/json"}',
    },
]


def seed(conn) -> None:
    # Fetch all org IDs
    orgs = conn.execute(text("SELECT id FROM organizations")).fetchall()
    if not orgs:
        log.warning("No organizations found — nothing to seed.")
        return

    log.info("Found %d organization(s).", len(orgs))

    for (org_id,) in orgs:
        log.info("  Seeding org %s ...", org_id)
        for p in PROMPTS:
            # Upsert template (DO NOTHING keeps existing data intact)
            conn.execute(text("""
                INSERT INTO prompt_templates
                    (id, organization_id, prompt_key, name, description, production_version, created_at, updated_at)
                VALUES
                    (:id, :org_id, :key, :name, :desc, 1, now(), now())
                ON CONFLICT (organization_id, prompt_key) DO NOTHING
            """), {
                "id": str(uuid.uuid4()),
                "org_id": str(org_id),
                "key": p["key"],
                "name": p["name"],
                "desc": p["description"],
            })

            # Fetch the template id (may have been inserted just now or already existed)
            tmpl_id = conn.execute(text("""
                SELECT id FROM prompt_templates
                WHERE organization_id = :org_id AND prompt_key = :key
            """), {"org_id": str(org_id), "key": p["key"]}).scalar()

            # Upsert version 1
            conn.execute(text("""
                INSERT INTO prompt_versions
                    (id, prompt_template_id, version, content, config, change_note, created_at)
                VALUES
                    (:id, :tmpl_id, 1, :content, :config::jsonb, 'Seeded by seed_prompt_baselines.py', now())
                ON CONFLICT (prompt_template_id, version) DO NOTHING
            """), {
                "id": str(uuid.uuid4()),
                "tmpl_id": str(tmpl_id),
                "content": p["content"],
                "config": p["config"],
            })

            # Ensure production_version is set (handles already-existing templates with NULL)
            conn.execute(text("""
                UPDATE prompt_templates
                SET production_version = 1
                WHERE id = :tmpl_id AND production_version IS NULL
            """), {"tmpl_id": str(tmpl_id)})

            log.info("    ✓ %s", p["key"])


with engine.begin() as conn:
    # Check tables exist before attempting seed
    tables = {
        row[0]
        for row in conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ))
    }
    missing = {"prompt_templates", "prompt_versions"} - tables
    if missing:
        log.error("Tables not found: %s — run alembic upgrade head first.", missing)
        sys.exit(1)

    seed(conn)

log.info("Done. Prompt baselines seeded successfully.")
