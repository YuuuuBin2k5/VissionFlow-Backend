"""VF-03.02a Commit 2 — Integration test verifying standard strategy calls narration handoff coordinator."""
from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from worker.application.render_strategies.standard_strategy import StandardRenderStrategy
from worker.domain.render_contract import RenderContract


class StandardStrategyIntegrationTests(unittest.IsolatedAsyncioTestCase):

    async def test_standard_strategy_invokes_handoff_coordinator(self) -> None:
        # Mock LLM details returned by LLMService.generate_video_details
        mock_details = MagicMock()
        mock_details.get.side_effect = lambda key, default=None: {
            "hook_text_3s": "Hook text",
            "full_voice_script": "This is a full voice script generated for testing that has sufficient length.",
            "scenes_layout_json": [{"scene_id": "scene-1", "visual_prompt": "Prompt", "duration": 5}],
            "seo_tags_metadata": {},
        }.get(key, default)

        # Mock LLM service
        mock_llm_svc = MagicMock()
        mock_llm_svc.generate_video_details.return_value = mock_details

        # Mock standard strategy direct imports
        mock_music_resolver = MagicMock()
        mock_music_resolver.return_value = ("/tmp/music.mp3", {"song_title": "Fake Song"})

        # Mock director services
        mock_style_director = MagicMock()
        mock_style_director.build_campaign_plan.return_value = {
            "quality_score": 90,
            "quality_warnings": [],
            "quality_passed": True,
            "selected_hook": "Hook text",
        }
        mock_retention_director = MagicMock()
        mock_retention_director.build_campaign_plan.return_value = {
            "selected_hook": "Hook text",
        }

        # Mock handoff coordinator
        mock_handoff_coordinator = MagicMock()

        patches = [
            patch("worker.services.llm_service.LLMService", return_value=mock_llm_svc),
            patch("worker.application.render_use_case.resolve_script_background_music", mock_music_resolver),
            patch("worker.services.video_style_director_service.VideoStyleDirectorService", return_value=mock_style_director),
            patch("worker.services.retention_director_service.RetentionDirectorService", return_value=mock_retention_director),
            patch("worker.application.narration_handoff.NarrationHandoffCoordinator", return_value=mock_handoff_coordinator),
            patch("worker.application.render_strategies.standard_strategy.log_realtime_progress"),
        ]

        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        strategy = StandardRenderStrategy()
        job = {
            "topic": "Education",
            "target_audience": "Students",
            "video_title_idea": "Math tricks",
        }
        metadata = {}
        contract = MagicMock(spec=RenderContract)
        contract.job_id = 12345
        contract.is_split_screen = False

        repo = MagicMock()

        # Run _run_llm which saves the script result
        env = {
            "VISIONFLOW_NARRATION_HANDOFF_MODE": "legacy",
            "APP_ENV": "development",
        }
        with patch.dict(os.environ, env, clear=True):
            await strategy._run_llm(job, metadata, contract, repo)

        # Verify our handoff coordinator was invoked!
        mock_handoff_coordinator.handle_narration.assert_called_once()
        args, kwargs = mock_handoff_coordinator.handle_narration.call_args
        self.assertEqual(args[0], 12345)  # job_id
        self.assertEqual(args[1], "Hook text")  # hook
        self.assertEqual(args[2], "This is a full voice script generated for testing that has sufficient length.")  # script
        self.assertEqual(args[3], [{"scene_id": "scene-1", "visual_prompt": "Prompt", "duration": 5}])  # scenes
        self.assertIn("voice_code", args[4])  # seo_tags


if __name__ == "__main__":
    unittest.main()
