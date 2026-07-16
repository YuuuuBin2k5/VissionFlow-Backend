from __future__ import annotations

import os
import uuid
from datetime import datetime, UTC
from typing import Any, Protocol

from app.infrastructure.overlay_uploads import OverlayUploadIssuer, OverlayUploadConfigurationError


class ShortFormReadinessRepository(Protocol):
    def check_gemini_active(self, organization_id: uuid.UUID) -> bool:
        """Return True if an active Gemini credential exists in the database for the organization."""
        ...

    def check_stock_media_active(self, organization_id: uuid.UUID) -> list[str]:
        """Return a list of active stock media provider names for the organization."""
        ...

    def check_youtube_connection_active(self, organization_id: uuid.UUID) -> bool:
        """Return True if an active YouTube publisher connection exists for the organization."""
        ...

    def check_prompts_baseline_active(self, organization_id: uuid.UUID, required_keys: list[str]) -> dict[str, bool]:
        """Return a dictionary mapping required prompt keys to their active status (has production_version set)."""
        ...


class GetShortFormReadiness:
    def __init__(self, repository: ShortFormReadinessRepository) -> None:
        self._repository = repository

    def execute(self, organization_id: uuid.UUID) -> dict[str, Any]:
        # 1. Gemini
        has_gemini = self._repository.check_gemini_active(organization_id)
        if not has_gemini:
            has_gemini = bool(os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEYS"))
        
        gemini_state = "ready" if has_gemini else "blocked"
        gemini_detail = "Gemini creative planning is configured and active." if has_gemini else "Gemini API key is missing. Add it to API Key Vault."
        
        # 2. Stock Media
        active_stocks = self._repository.check_stock_media_active(organization_id)
        fallback_stocks = []
        if os.getenv("PEXELS_API_KEY"):
            fallback_stocks.append("pexels")
        if os.getenv("PIXABAY_API_KEY"):
            fallback_stocks.append("pixabay")
        if os.getenv("COVERR_API_KEY"):
            fallback_stocks.append("coverr")
        
        all_stocks = sorted(list(set(active_stocks + fallback_stocks)))
        has_stock = len(all_stocks) > 0
        stock_state = "ready" if has_stock else "blocked"
        stock_detail = f"Stock media configured: {', '.join(all_stocks)}." if has_stock else "No active stock media provider found. Add one (Pexels/Pixabay/Coverr) to API Key Vault."

        # 3. R2 Storage
        try:
            OverlayUploadIssuer.from_env()
            r2_state = "ready"
            r2_detail = "R2 storage configuration is valid."
        except OverlayUploadConfigurationError as exc:
            r2_state = "blocked"
            r2_detail = str(exc)

        # 4. Render Runner
        runner_state = "unknown"
        runner_detail = "Live status cannot be verified from backend. Follow the instructions to dispatch the runner."

        # 5. Prompt Baseline
        required_prompts = ["short_video_scene_planner", "short_video_visual_art_director"]
        prompt_status = self._repository.check_prompts_baseline_active(organization_id, required_prompts)
        missing_prompts = [k for k in required_prompts if not prompt_status.get(k, False)]
        has_prompts = len(missing_prompts) == 0
        prompt_state = "ready" if has_prompts else "blocked"
        prompt_detail = "Required prompt templates are active and promoted." if has_prompts else f"Required prompt templates ({', '.join(missing_prompts)}) must be created and promoted in the Agent Prompts registry."

        # 6. YouTube
        has_youtube = self._repository.check_youtube_connection_active(organization_id)
        youtube_state = "ready" if has_youtube else "degraded"
        youtube_detail = "YouTube channel connection is active." if has_youtube else "No connected YouTube channel. Highly recommended to connect a channel for publication."

        checks = [
            {
                "key": "creative_provider",
                "state": gemini_state,
                "label": "Gemini creative planning",
                "detail": gemini_detail,
                "remediation": {
                    "kind": "tab",
                    "target": "credential_vault"
                } if gemini_state == "blocked" else None
            },
            {
                "key": "stock_media",
                "state": stock_state,
                "label": "Stock media provider",
                "detail": stock_detail,
                "remediation": {
                    "kind": "tab",
                    "target": "credential_vault"
                } if stock_state == "blocked" else None
            },
            {
                "key": "r2_storage",
                "state": r2_state,
                "label": "R2 storage connection",
                "detail": r2_detail,
                "remediation": None
            },
            {
                "key": "render_runner",
                "state": runner_state,
                "label": "Free render runner",
                "detail": runner_detail,
                "remediation": {
                    "kind": "url",
                    "target": "https://github.com/YuuuuBin2k5/YuuuBin_Agent_Bot/actions/workflows/visionflow-render-free.yml"
                }
            },
            {
                "key": "prompt_baseline",
                "state": prompt_state,
                "label": "Prompt baseline",
                "detail": prompt_detail,
                "remediation": {
                    "kind": "tab",
                    "target": "agent_prompts"
                } if prompt_state == "blocked" else None
            },
            {
                "key": "youtube_connection",
                "state": youtube_state,
                "label": "YouTube channel connection",
                "detail": youtube_detail,
                "remediation": {
                    "kind": "tab",
                    "target": "publication_queue"
                } if youtube_state == "degraded" else None
            }
        ]

        is_blocked = any(c["state"] == "blocked" for c in checks if c["key"] not in ("youtube_connection", "render_runner"))
        overall_state = "blocked" if is_blocked else "degraded"

        creation_ready = (
            gemini_state == "ready" and
            stock_state == "ready" and
            r2_state == "ready" and
            prompt_state == "ready"
        )
        render_dispatch_ready = False

        return {
            "organization_id": str(organization_id),
            "profile": "short_vertical",
            "overall": overall_state,
            "creation_ready": creation_ready,
            "render_dispatch_ready": render_dispatch_ready,
            "checks": checks,
            "checked_at": datetime.now(UTC).isoformat()
        }
