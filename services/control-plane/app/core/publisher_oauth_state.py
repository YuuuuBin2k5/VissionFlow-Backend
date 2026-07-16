from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid

from app.core.youtube_publisher import YouTubePublisherSettings


def issue_state(organization_id: uuid.UUID, subject: str, *, now: int | None = None) -> tuple[str, str, int]:
    settings = YouTubePublisherSettings.from_env()
    issued = int(time.time() if now is None else now)
    expires = issued + 600
    nonce = secrets.token_urlsafe(24)
    body = {"o": str(organization_id), "s": subject, "n": nonce, "e": expires}
    encoded = base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":"), sort_keys=True).encode()).decode().rstrip("=")
    signature = hmac.new(settings.oauth_state_key, encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}", hashlib.sha256(nonce.encode()).hexdigest(), expires


def verify_state(state: str, *, now: int | None = None) -> dict[str, str | int]:
    try:
        encoded, signature = state.split(".", 1)
        settings = YouTubePublisherSettings.from_env()
        expected = hmac.new(settings.oauth_state_key, encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected): raise ValueError
        payload = json.loads(base64.urlsafe_b64decode(encoded + "==="))
        if not isinstance(payload, dict) or int(payload["e"]) < int(time.time() if now is None else now): raise ValueError
        if not all(isinstance(payload.get(key), str) and payload[key] for key in ("o", "s", "n")): raise ValueError
        uuid.UUID(payload["o"])
        return payload
    except Exception as exc:
        raise ValueError("OAuth state is invalid or expired") from exc
