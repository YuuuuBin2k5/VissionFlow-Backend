import os
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from worker.services.visual_keyword_extractor import VisualKeywordExtractor
from worker.services.asset_service import AssetService, StockVideoCandidate, HISTORY_LEDGER_FILE


class TestVisualKeywordExtractor:
    def test_extract_keywords_heuristics(self):
        extractor = VisualKeywordExtractor()
        # Mock client to None to test heuristic NLP fallback
        extractor.client = None

        prompt = "Cappy Para sitting quietly near a campfire on a dark rocky coast watching burning ships in the ocean"
        keywords = extractor.extract_keywords(prompt, scene_index=1)

        assert isinstance(keywords, list)
        assert len(keywords) > 0
        # Ensure noise words like 'cappy', 'para' are stripped out
        joined = " ".join(keywords).lower()
        assert "cappy" not in joined
        assert "para" not in joined

    def test_extract_keywords_empty(self):
        extractor = VisualKeywordExtractor()
        keywords = extractor.extract_keywords("", scene_index=1)
        assert keywords == ["aesthetic vertical", "nature vertical", "abstract vertical"]


class TestSmartBrollEngine:
    def test_ledger_marking_and_loading(self, tmp_path):
        ledger_path = tmp_path / "test_ledger.json"
        with patch("worker.services.asset_service.HISTORY_LEDGER_FILE", ledger_path):
            service = AssetService()

            # Initial ledger should be empty
            assert len(service._load_used_assets()) == 0

            # Mark assets as used
            service._mark_asset_used("https://videos.pexels.com/test1.mp4")
            service._mark_asset_used("https://videos.pexels.com/test2.mp4")

            used_set = service._load_used_assets()
            assert "https://videos.pexels.com/test1.mp4" in used_set
            assert "https://videos.pexels.com/test2.mp4" in used_set

    def test_deduplication_score_penalty(self, tmp_path):
        ledger_path = tmp_path / "test_ledger.json"
        with patch("worker.services.asset_service.HISTORY_LEDGER_FILE", ledger_path):
            service = AssetService()
            service._mark_asset_used("https://videos.pexels.com/used_clip.mp4")

            score_fresh = service._score_stock_candidate(
                query="nature",
                duration=15,
                width=1080,
                height=1920,
                metadata_text="nature forest",
                candidate_link="https://videos.pexels.com/fresh_clip.mp4"
            )

            score_used = service._score_stock_candidate(
                query="nature",
                duration=15,
                width=1080,
                height=1920,
                metadata_text="nature forest",
                candidate_link="https://videos.pexels.com/used_clip.mp4"
            )

            # Used clip should receive a -100 score penalty
            assert score_fresh - score_used == 100

    def test_round_robin_candidate_blending(self):
        service = AssetService()

        # Mock providers to return dummy candidates
        cand1 = StockVideoCandidate("pexels", "sea", "https://pexels.com/1.mp4", "url1", 10, 1080, 1920, 80)
        cand2 = StockVideoCandidate("pixabay", "sea", "https://pixabay.com/2.mp4", "url2", 10, 1080, 1920, 90)
        cand3 = StockVideoCandidate("coverr", "sea", "https://coverr.co/3.mp4", "url3", 10, 1080, 1920, 75)

        with patch.object(service, "_search_pexels_candidates", return_value=[cand1]), \
             patch.object(service, "_search_pixabay_candidates", return_value=[cand2]), \
             patch.object(service, "_search_coverr_candidates", return_value=[cand3]):

            candidates = service._find_video_candidates("sea", count=3)

            assert len(candidates) == 3
            providers = {c.provider for c in candidates}
            assert "pexels" in providers
            assert "pixabay" in providers
            assert "coverr" in providers
