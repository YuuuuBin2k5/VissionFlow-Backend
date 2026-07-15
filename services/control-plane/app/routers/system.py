from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.infrastructure.database import get_engine


router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict[str, str]:
    settings = Settings.from_env()
    return {"status": "ok", "service": "visionflow-control-plane", "environment": settings.app_env}


@router.get("/ready")
def ready() -> dict[str, str]:
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="PostgreSQL is unavailable") from exc
    return {"status": "ready", "database": "postgresql"}
