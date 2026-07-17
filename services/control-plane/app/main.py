import os
import uuid
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app.core.config import Settings
from app.routers import auth, credentials, integrations, prompts, system, workflows, creative_sessions

logger = logging.getLogger(__name__)

settings = Settings.from_env()
app = FastAPI(title="VisionFlow Control Plane", version="0.1.0")

origins = [origin.strip().rstrip("/") for origin in os.getenv("VISIONFLOW_WEB_ORIGINS", "").split(",") if origin.strip()]
if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
    )

app.include_router(system.router, prefix=settings.api_prefix)
app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(workflows.router, prefix=settings.api_prefix)
app.include_router(prompts.router, prefix=settings.api_prefix)
app.include_router(credentials.router, prefix=settings.api_prefix)
app.include_router(integrations.router, prefix=settings.api_prefix)
app.include_router(creative_sessions.router, prefix=settings.api_prefix)


# ---------------------------------------------------------------------------
# Startup: seed missing prompt baselines for all existing organizations
# ---------------------------------------------------------------------------

_PLANNER_CONTENT = """\
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

_DIRECTOR_CONTENT = """\
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

_BASELINE_PROMPTS = [
    {
        "key": "short_video_scene_planner",
        "name": "Short video scene planner",
        "description": "Acts as the scene planning director for the short-video renderer.",
        "content": _PLANNER_CONTENT,
        "config": {"model": "gemini-1.5-flash", "temperature": 0.7, "response_mime_type": "application/json"},
    },
    {
        "key": "short_video_visual_art_director",
        "name": "Short video visual art director",
        "description": "Acts as the visual art director for media search and render prompts.",
        "content": _DIRECTOR_CONTENT,
        "config": {"model": "gemini-1.5-flash", "temperature": 0.4, "response_mime_type": "application/json"},
    },
]


@app.on_event("startup")
async def _seed_prompt_baselines() -> None:
    """Idempotent: creates prompt tables if missing, then seeds baselines for all orgs."""
    import json
    from sqlalchemy import text as sa_text
    from app.infrastructure.database import get_engine

    engine = get_engine()
    try:
        with engine.begin() as conn:
            logger.info("startup seed: checking prompt registry tables...")

            # ── Step 1: Create tables if they don't exist ──────────────────
            conn.execute(sa_text("""
                CREATE TABLE IF NOT EXISTS prompt_templates (
                    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                    prompt_key      VARCHAR(100) NOT NULL,
                    name            VARCHAR(160) NOT NULL,
                    description     TEXT NOT NULL,
                    production_version INTEGER,
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                    CONSTRAINT uq_prompt_template_key UNIQUE (organization_id, prompt_key)
                )
            """))

            conn.execute(sa_text("""
                CREATE TABLE IF NOT EXISTS prompt_versions (
                    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    prompt_template_id UUID NOT NULL REFERENCES prompt_templates(id) ON DELETE CASCADE,
                    version            INTEGER NOT NULL,
                    content            TEXT NOT NULL,
                    config             JSONB NOT NULL DEFAULT '{}',
                    change_note        VARCHAR(500),
                    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
                    CONSTRAINT uq_prompt_version UNIQUE (prompt_template_id, version)
                )
            """))

            logger.info("startup seed: tables ready.")

            # ── Step 2: Load orgs ──────────────────────────────────────────
            orgs = conn.execute(sa_text("SELECT id FROM organizations")).fetchall()
            if not orgs:
                logger.info("startup seed: no organizations found, nothing to seed.")
                return

            # ── Step 3: Early-exit if all baselines already present ────────
            expected = len(orgs) * len(_BASELINE_PROMPTS)
            existing = conn.execute(sa_text("""
                SELECT COUNT(*) FROM prompt_templates
                WHERE prompt_key = ANY(:keys)
            """), {"keys": [p["key"] for p in _BASELINE_PROMPTS]}).scalar() or 0

            if existing >= expected:
                logger.info("startup seed: all %d prompt baselines already present, skipping.", existing)
                return

            # ── Step 4: Seed missing baselines ────────────────────────────
            seeded = 0
            for (org_id,) in orgs:
                for p in _BASELINE_PROMPTS:
                    conn.execute(sa_text("""
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

                    tmpl_id = conn.execute(sa_text("""
                        SELECT id FROM prompt_templates
                        WHERE organization_id = :org_id AND prompt_key = :key
                    """), {"org_id": str(org_id), "key": p["key"]}).scalar()

                    conn.execute(sa_text("""
                        INSERT INTO prompt_versions
                            (id, prompt_template_id, version, content, config, change_note, created_at)
                        VALUES
                            (:id, :tmpl_id, 1, :content, :config::jsonb, 'Auto-seeded on startup', now())
                        ON CONFLICT (prompt_template_id, version) DO NOTHING
                    """), {
                        "id": str(uuid.uuid4()),
                        "tmpl_id": str(tmpl_id),
                        "content": p["content"],
                        "config": json.dumps(p["config"]),
                    })

                    conn.execute(sa_text("""
                        UPDATE prompt_templates
                        SET production_version = 1
                        WHERE id = :tmpl_id AND production_version IS NULL
                    """), {"tmpl_id": str(tmpl_id)})

                    seeded += 1

            logger.info("startup seed: seeded %d prompt baseline(s) across %d org(s).", seeded, len(orgs))

    except Exception as exc:
        # Never block server startup due to seed failure
        logger.error("startup seed failed (non-fatal): %s", exc, exc_info=True)


def _normalize_trace_id(request_id: str | None) -> str:
    normalized = (request_id or "").replace("-", "")
    if len(normalized) == 32 and all(character in "0123456789abcdefABCDEF" for character in normalized):
        return normalized.lower()
    return uuid.uuid4().hex


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    request_id = request.headers.get("X-Request-ID") or request.headers.get("x-request-id")
    trace_id = _normalize_trace_id(request_id) if request_id else uuid.uuid4().hex

    code = "HTTP_ERROR"
    if exc.status_code == 401:
        code = "UNAUTHORIZED"
    elif exc.status_code == 403:
        code = "PERMISSION_DENIED"
    elif exc.status_code == 404:
        code = "NOT_FOUND"
    elif exc.status_code == 409:
        code = "CONFLICT"
    elif exc.status_code == 422:
        code = "VALIDATION_ERROR"

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": code,
            "message": exc.detail,
            "trace_id": trace_id,
            "detail": exc.detail,
        }
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    request_id = request.headers.get("X-Request-ID") or request.headers.get("x-request-id")
    trace_id = _normalize_trace_id(request_id) if request_id else uuid.uuid4().hex

    return JSONResponse(
        status_code=422,
        content={
            "code": "VALIDATION_ERROR",
            "message": "Validation failed",
            "trace_id": trace_id,
            "detail": exc.errors(),
        }
    )


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    request_id = request.headers.get("X-Request-ID") or request.headers.get("x-request-id")
    trace_id = _normalize_trace_id(request_id) if request_id else uuid.uuid4().hex

    import sys
    import traceback
    print(f"Unhandled Exception [Trace ID: {trace_id}]: {exc}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)

    return JSONResponse(
        status_code=500,
        content={
            "code": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected error occurred",
            "trace_id": trace_id,
            "detail": None,
        }
    )
