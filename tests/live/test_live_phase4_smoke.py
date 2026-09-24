"""
Live External Smoke Test Suite: Phase 4 Visual Planner & Pexels Stock Adapter
Isolated with @pytest.mark.live and skipped by default in regular offline pytest runs.
Runs real live calls to Gemini and Pexels API only when valid API keys are present.
"""

from __future__ import annotations

import asyncio
import os
import pytest

from production.contracts import (
    RightsState,
    SceneNarration,
    ScriptPlan,
    VisualPlan,
    VisualRole,
)
from production.visual_planner import GeminiVisualPlannerProvider, VisualPlanner
from production.asset_resolver import PexelsStockAdapter, asset_resolver


@pytest.mark.live
class TestLivePhase4Smoke:

    @pytest.mark.skipif(
        not os.getenv("PEXELS_API_KEY") or os.getenv("PEXELS_API_KEY").startswith("YOUR_"),
        reason="PEXELS_API_KEY is not set or is placeholder",
    )
    def test_live_pexels_video_search(self):
        adapter = PexelsStockAdapter()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            candidates = loop.run_until_complete(
                adapter.search_stock("bamboo craftsman workshop", limit=3, prefer_portrait=True)
            )
            assert len(candidates) > 0
            first = candidates[0]
            assert first.provider == "pexels_stock"
            assert first.rights_state == RightsState.APPROVED_STOCK
            assert first.media_url is not None
            assert first.duration_sec > 0
        finally:
            loop.close()

    @pytest.mark.skipif(
        not os.getenv("GEMINI_API_KEY") or os.getenv("VISIONFLOW_USE_DEV_REPOSITORIES") == "1",
        reason="GEMINI_API_KEY not set or dev mode active",
    )
    def test_live_gemini_visual_planner(self):
        script = ScriptPlan(
            title="Đũa tre thủ công",
            full_script="Nghệ nhân dùng dao gọt từng thanh tre già để tạo hình đôi đũa tinh xảo.",
            scenes=[
                SceneNarration(
                    scene_index=1,
                    narration="Nghệ nhân dùng dao gọt từng thanh tre già để tạo hình đôi đũa tinh xảo.",
                    estimated_speech_duration_sec=4.0,
                )
            ],
            total_word_count=15,
            estimated_total_duration_sec=4.0,
        )
        planner = VisualPlanner(GeminiVisualPlannerProvider())
        plan = planner.generate_visual_plan(script)
        assert len(plan.intents) >= 1
        intent = plan.intents[0]
        assert intent.search_query_en != ""
        assert len(intent.subjects) > 0
