"""
Unit and Parity Tests for OpenCut Schema Conversion (Section 0.2, 25).
Verifies that canonical backend export_opencut_timeline produces
deterministic, schema-compliant OpenCut project JSON matching frontend expectations.
"""

import unittest
from production.contracts import (
    AudioClipPlan,
    AudioTrackPlan,
    EditorPlan,
    EditorPlanType,
    ScenePlan,
    ShotPlan,
    SubtitleChunkPlan,
    SubtitleTrackPlan,
)
from production.editor_planner import editor_planner


class TestOpenCutParity(unittest.TestCase):
    def setUp(self):
        self.shot1 = ShotPlan(
            shot_id="shot_1_1",
            shot_index=1,
            asset_id="asset_001",
            source_id="src_001",
            provider="pexels_stock",
            media_url="https://example.com/video1.mp4",
            timeline_start=0.0,
            timeline_end=3.0,
            duration_sec=3.0,
            asset_trim_start=1.0,
            asset_trim_end=4.0,
            visual_role="HOOK",
            transition_out="cut",
            transition_duration_sec=0.0,
            motion_effect="static_hold",
        )
        self.shot2 = ShotPlan(
            shot_id="shot_1_2",
            shot_index=2,
            asset_id="asset_002",
            source_id="src_002",
            provider="scene_library",
            media_url="https://example.com/video2.mp4",
            timeline_start=3.0,
            timeline_end=6.0,
            duration_sec=3.0,
            asset_trim_start=0.0,
            asset_trim_end=3.0,
            visual_role="PROCESS",
            transition_out="crossfade",
            transition_duration_sec=0.3,
            motion_effect="ken_burns_zoom_in",
        )
        self.scene = ScenePlan(
            scene_id="scene_001",
            scene_index=1,
            narration="Khám phá bí mật công nghệ vi mạch.",
            actual_duration_seconds=6.0,
            timeline_start=0.0,
            timeline_end=6.0,
            audio_file_path="/tmp/audio_001.wav",
            shots=[self.shot1, self.shot2],
        )
        self.audio_clip = AudioClipPlan(
            clip_id="clip_aud_1",
            type="voice",
            scene_id="scene_001",
            audio_asset_id="aud_001",
            file_path="/tmp/audio_001.wav",
            timeline_start=0.0,
            timeline_end=6.0,
            duration_sec=6.0,
            volume=1.0,
            ducking_factor=0.15,
        )
        self.sub1 = SubtitleChunkPlan(
            chunk_id="sub_01",
            text="Khám phá bí mật",
            start_sec=0.0,
            end_sec=2.8,
            duration_sec=2.8,
            scene_id="scene_001",
        )
        self.sub2 = SubtitleChunkPlan(
            chunk_id="sub_02",
            text="công nghệ vi mạch.",
            start_sec=2.8,
            end_sec=6.0,
            duration_sec=3.2,
            scene_id="scene_001",
        )
        self.editor_plan = EditorPlan(
            plan_id="plan_parity_test_01",
            run_id="run_parity_01",
            script_version="1.0",
            plan_type=EditorPlanType.FINAL.value,
            duration_seconds=6.0,
            aspect_ratio="9:16",
            timeline_drift_ms=0.0,
            scenes=[self.scene],
            audio_track=AudioTrackPlan(voice_clips=[self.audio_clip]),
            subtitle_track=SubtitleTrackPlan(chunks=[self.sub1, self.sub2]),
            is_render_ready=True,
        )

    def test_canonical_opencut_export_structure(self):
        """Backend export_opencut_timeline must generate exact OpenCut 1.0.0 schema."""
        opencut_json = editor_planner.export_opencut_timeline(self.editor_plan)

        # Root fields
        self.assertEqual(opencut_json["version"], "1.0.0-opencut")
        self.assertEqual(opencut_json["aspectRatio"], "9:16")
        self.assertEqual(opencut_json["fps"], 30)
        self.assertEqual(opencut_json["totalDurationSec"], 6.0)

        # Metadata
        meta = opencut_json["metadata"]
        self.assertEqual(meta["plan_id"], "plan_parity_test_01")
        self.assertEqual(meta["plan_type"], "FINAL_EDITOR_PLAN")
        self.assertTrue(meta["is_render_ready"])
        self.assertEqual(meta["timeline_drift_ms"], 0.0)

        # Tracks
        tracks = opencut_json["tracks"]
        self.assertEqual(len(tracks), 3)

        v_track = next((t for t in tracks if t["id"] == "track_video_main"), None)
        a_track = next((t for t in tracks if t["id"] == "track_audio_voice"), None)
        t_track = next((t for t in tracks if t["id"] == "track_text_captions"), None)

        self.assertIsNotNone(v_track)
        self.assertIsNotNone(a_track)
        self.assertIsNotNone(t_track)

        # Video Clips parity
        self.assertEqual(len(v_track["clips"]), 2)
        clip1 = v_track["clips"][0]
        self.assertEqual(clip1["id"], "shot_1_1")
        self.assertEqual(clip1["startSec"], 0.0)
        self.assertEqual(clip1["durationSec"], 3.0)
        self.assertEqual(clip1["trimStartSec"], 1.0)
        self.assertEqual(clip1["trimEndSec"], 4.0)
        self.assertEqual(clip1["motionEffect"], "static_hold")

        # Audio Clips parity
        self.assertEqual(len(a_track["clips"]), 1)
        aclip = a_track["clips"][0]
        self.assertEqual(aclip["startSec"], 0.0)
        self.assertEqual(aclip["durationSec"], 6.0)
        self.assertEqual(aclip["duckingFactor"], 0.15)

        # Text Clips parity
        self.assertEqual(len(t_track["clips"]), 2)
        subclip1 = t_track["clips"][0]
        self.assertEqual(subclip1["startSec"], 0.0)
        self.assertEqual(subclip1["durationSec"], 2.8)
        self.assertEqual(subclip1["textData"]["content"], "Khám phá bí mật")
        self.assertEqual(subclip1["textData"]["presetStyle"], "hormozi")


if __name__ == "__main__":
    unittest.main()
