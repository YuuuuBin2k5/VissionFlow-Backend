import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings
from app.routers import auth, prompts, system, workflows


settings = Settings.from_env()
app = FastAPI(title="VisionFlow Control Plane", version="0.1.0")
origins = [origin.strip().rstrip("/") for origin in os.getenv("VISIONFLOW_WEB_ORIGINS", "").split(",") if origin.strip()]
if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
    )
app.include_router(system.router, prefix=settings.api_prefix)
app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(workflows.router, prefix=settings.api_prefix)
app.include_router(prompts.router, prefix=settings.api_prefix)


from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
import uuid

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
