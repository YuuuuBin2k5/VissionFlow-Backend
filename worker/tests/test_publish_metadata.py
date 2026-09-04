from __future__ import annotations

import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT))

from worker.domain.caption_policy import build_high_converting_description, detect_video_genre
from worker.domain.publish_metadata import append_required_attribution, resolve_publish_metadata


class PublishMetadataResolutionTests(unittest.TestCase):
    def test_a_explicit_content_description_wins_without_fallback(self) -> None:
        resolved = resolve_publish_metadata(
            content_metadata={"youtube": {"description": "CUSTOM AI DESCRIPTION"}},
            fallback={"youtube": {"description": "generic fallback"}},
        )
        self.assertEqual("CUSTOM AI DESCRIPTION", resolved.description.value)
        self.assertEqual("content_ai", resolved.description.source)

    def test_b_user_edit_wins_over_content_package(self) -> None:
        resolved = resolve_publish_metadata(
            user_metadata={"youtube": {"description": "B"}},
            content_metadata={"youtube": {"description": "A"}},
        )
        self.assertEqual("B", resolved.description.value)
        self.assertEqual("user", resolved.description.source)

    def test_c_old_payload_gets_a_generated_fallback(self) -> None:
        fallback = build_high_converting_description("Old JSON title", "One useful sentence. Another useful sentence.")
        resolved = resolve_publish_metadata(fallback={"youtube": {"title": "Old JSON title", "description": fallback}})
        self.assertEqual("generated_fallback", resolved.description.source)
        self.assertTrue(resolved.description.value)

    def test_d_unknown_explicit_genre_is_preserved(self) -> None:
        self.assertEqual(
            "social_psychology_cultural_explainer",
            detect_video_genre("A life lesson", "philosophy and wisdom", "social_psychology_cultural_explainer"),
        )

    def test_e_title_is_never_auto_appended_with_shorts(self) -> None:
        resolved = resolve_publish_metadata(content_metadata={"youtube": {"title": "Why We Watch Morning Routines"}})
        self.assertEqual("Why We Watch Morning Routines", resolved.title.value)

    def test_f_no_irrelevant_default_tags_are_invented(self) -> None:
        resolved = resolve_publish_metadata(fallback={"youtube": {"title": "Morning routine psychology"}})
        self.assertIsNone(resolved.tags)

    def test_g_hashtags_are_normalized_and_deduplicated(self) -> None:
        resolved = resolve_publish_metadata(content_metadata={"youtube": {"hashtags": ["#MorningRoutine", "#morningroutine", "MorningRoutine"]}})
        self.assertEqual(["#MorningRoutine"], resolved.hashtags.value)

    def test_h_music_license_is_not_invented(self) -> None:
        description, issues = append_required_attribution("Video text", {"track": "Unknown", "license_type": "unknown"})
        self.assertEqual("Video text", description)
        self.assertEqual([], issues)
        self.assertNotIn("Creative Commons", build_high_converting_description("Title", "A script sentence. Another script sentence.", {"bgm_info": {"credit": "Artist"}}))

    def test_i_publishing_metadata_never_mutates_narration(self) -> None:
        narration = "The final narration remains untouched."
        resolve_publish_metadata(content_metadata={"youtube": {"pinned_comment": "Comment below"}})
        self.assertEqual("The final narration remains untouched.", narration)

    def test_j_platform_specific_fields_do_not_cross_over(self) -> None:
        content = {
            "youtube": {"description": "YouTube description"},
            "tiktok": {"caption": "TikTok caption"},
        }
        youtube = resolve_publish_metadata(content_metadata=content, platform="youtube")
        tiktok = resolve_publish_metadata(content_metadata=content, platform="tiktok")
        self.assertEqual("YouTube description", youtube.description.value)
        self.assertEqual("TikTok caption", tiktok.caption.value)


if __name__ == "__main__":
    unittest.main()
