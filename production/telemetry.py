"""
Cost & Latency Telemetry for VisionFlow Auto Production System (Phase 7 - Section 18, 19, 20).
Tracks granular compute, LLM/VLM, TTS, and stock API costs per video and output minute,
computes P50/P95 stage latencies, and logs config-driven model provider routing.
"""

from __future__ import annotations

import logging
import statistics
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from production.contracts import (
    CostTelemetry,
    LatencyTelemetry,
    ProductionRun,
    ProviderRoutingRecord,
)

logger = logging.getLogger("visionflow.production.telemetry")


# Standard reference pricing (USD)
PRICING_TABLE = {
    "gemini-1.5-flash": {"prompt_1k": 0.000075, "completion_1k": 0.0003},
    "gemini-1.5-pro": {"prompt_1k": 0.00125, "completion_1k": 0.005},
    "gpt-4o": {"prompt_1k": 0.005, "completion_1k": 0.015},
    "text-embedding-004": {"per_1k": 0.000025},
    "edge_tts": {"per_char": 0.000000},  # Free
    "azure_tts": {"per_char": 0.000016},
    "pexels_stock": {"per_request": 0.000},  # Free API tier
    "cpu_render": {"per_second": 0.000015},
}


class CostTracker:
    """
    Tracks and aggregates dollar costs and compute resource utilization per video.
    """

    def __init__(self):
        self._records: List[ProviderRoutingRecord] = []

    def record_llm_call(
        self,
        stage: str,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int,
        fallback_used: bool = False,
        fallback_reason: Optional[str] = None,
    ) -> ProviderRoutingRecord:
        rates = PRICING_TABLE.get(model, PRICING_TABLE["gemini-1.5-flash"])
        cost = (prompt_tokens / 1000.0 * rates["prompt_1k"]) + (completion_tokens / 1000.0 * rates["completion_1k"])
        rec = ProviderRoutingRecord(
            stage=stage,
            provider=provider,
            model=model,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            latency_ms=latency_ms,
            cost_usd=round(cost, 6),
        )
        self._records.append(rec)
        return rec

    def build_telemetry(
        self,
        video_duration_seconds: float,
        render_seconds: float = 0.0,
        tts_chars: int = 0,
        stock_requests: int = 0,
    ) -> CostTelemetry:
        llm_cost = sum(r.cost_usd for r in self._records if "gemini" in r.model or "gpt" in r.model)
        vlm_cost = sum(r.cost_usd for r in self._records if "vision" in r.stage or "vlm" in r.stage)
        embed_cost = sum(r.cost_usd for r in self._records if "embedding" in r.stage)
        tts_cost = tts_chars * PRICING_TABLE["azure_tts"]["per_char"]
        render_cost = render_seconds * PRICING_TABLE["cpu_render"]["per_second"]
        total = llm_cost + vlm_cost + embed_cost + tts_cost + render_cost

        video_mins = max(0.1, video_duration_seconds / 60.0)
        cost_per_min = total / video_mins

        return CostTelemetry(
            total_cost_usd=round(total, 4),
            cost_per_video=round(total, 4),
            cost_per_output_minute=round(cost_per_min, 4),
            llm_cost_usd=round(llm_cost, 4),
            vlm_cost_usd=round(vlm_cost, 4),
            embedding_cost_usd=round(embed_cost, 4),
            tts_cost_usd=round(tts_cost, 4),
            stock_api_cost_usd=0.0,
            render_compute_seconds=round(render_seconds, 2),
            tts_characters=tts_chars,
            stock_assets_requested=stock_requests,
            records=list(self._records),
        )


class LatencyTracker:
    """
    Measures pipeline execution durations per stage and computes P50/P95 distributions.
    """

    @staticmethod
    def calculate_telemetry(stage_durations: Dict[str, int]) -> LatencyTelemetry:
        if not stage_durations:
            return LatencyTelemetry()

        values = sorted(stage_durations.values())
        total_ms = sum(values)

        p50 = statistics.median(values) if values else 0.0
        # P95 estimation
        idx_p95 = int(len(values) * 0.95)
        p95 = values[min(idx_p95, len(values) - 1)]

        bottleneck = max(stage_durations.items(), key=lambda x: x[1])[0] if stage_durations else None

        return LatencyTelemetry(
            total_pipeline_duration_ms=total_ms,
            stage_durations_ms=stage_durations,
            p50_stage_duration_ms=round(p50, 1),
            p95_stage_duration_ms=round(p95, 1),
            bottleneck_stage=bottleneck,
        )


class ProviderRouter:
    """
    Config-driven routing for model providers with strict fallback provenance.
    """

    def __init__(self, primary_provider: str = "gemini", secondary_provider: str = "local_heuristic"):
        self.primary_provider = primary_provider
        self.secondary_provider = secondary_provider

    def route_call(self, stage: str, allow_cloud: bool = True) -> Dict[str, Any]:
        if allow_cloud and self.primary_provider == "gemini":
            return {
                "provider": "gemini",
                "model": "gemini-1.5-flash",
                "is_fallback": False,
            }
        return {
            "provider": self.secondary_provider,
            "model": "rule_based_deterministic",
            "is_fallback": True,
            "fallback_reason": "CLOUD_NOT_PERMITTED_OR_UNAVAILABLE",
        }


# Global instances
cost_tracker = CostTracker()
latency_tracker = LatencyTracker()
provider_router = ProviderRouter()
