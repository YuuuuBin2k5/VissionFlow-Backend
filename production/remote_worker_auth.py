"""Dedicated identity-bound credentials, never a general API credential."""
import hashlib
import hmac
import json
import os
from dataclasses import dataclass

from fastapi import Header, HTTPException


def worker_credentials() -> dict[str, str]:
    raw = os.getenv("VISIONFLOW_WORKER_TOKENS", "")
    if raw:
        try:
            values = json.loads(raw)
        except ValueError:
            raise HTTPException(503, "Invalid worker credential configuration") from None
    else:
        worker_id, token = os.getenv("VISIONFLOW_WORKER_ID"), os.getenv("VISIONFLOW_WORKER_TOKEN")
        values = {worker_id: token} if worker_id and token else {}
    if (not isinstance(values, dict) or any(not isinstance(k, str) or not isinstance(v, str)
            or len(v) < 32 or len(v) > 4096 for k, v in values.items())
            or len(set(values.values())) != len(values)):
        raise HTTPException(503, "Invalid worker credential configuration")
    return values


def token_matches(token: str, expected: str) -> bool:
    return hmac.compare_digest(hashlib.sha256(token.encode()).digest(), hashlib.sha256(expected.encode()).digest())


def is_worker_credential(authorization: str) -> bool:
    scheme, _, token = authorization.partition(" ")
    return scheme.lower() == "bearer" and any(token_matches(token, value) for value in worker_credentials().values())


@dataclass(frozen=True)
class WorkerIdentity:
    worker_id: str
    capabilities: tuple[str, ...] = ("canonical-v1", "ffmpeg", "h264", "aac")
    status: str = "UNREGISTERED"


def require_render_worker(authorization: str = Header(default=""),
                          x_visionflow_worker_id: str = Header(default="")) -> WorkerIdentity:
    scheme, _, token = authorization.partition(" ")
    expected = worker_credentials().get(x_visionflow_worker_id, "")
    if scheme.lower() != "bearer" or not expected or not token_matches(token, expected):
        raise HTTPException(401, "Invalid render worker credential")
    return WorkerIdentity(worker_id=x_visionflow_worker_id)


async def worker_scope_middleware(request, call_next):
    from fastapi.responses import JSONResponse
    # Also reject a valid worker bearer without its ID header on general routes.
    if not request.url.path.startswith("/api/v1/render-workers/"):
        try:
            is_worker = bool(request.headers.get("x-visionflow-worker-id")) or is_worker_credential(request.headers.get("authorization", ""))
        except HTTPException:
            is_worker = bool(request.headers.get("x-visionflow-worker-id"))
        if is_worker:
            return JSONResponse(status_code=403, content={"detail": "Worker credentials are scoped to render-worker routes"})
    return await call_next(request)
