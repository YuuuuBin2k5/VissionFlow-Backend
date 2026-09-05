import unittest

from worker.domain.dubbing_contract import (
    DUBBING_PACKAGE_VERSION,
    build_dubbing_workflow_package,
    legacy_seo_to_publish_metadata,
    record_timing_qc,
    select_render_text,
)


class DubbingContractTests(unittest.TestCase):
    def test_faithful_is_default_and_adaptation_is_opt_in(self):
        package = build_dubbing_workflow_package({"voice_code": "voice-a"}, source_asset_id="asset-1")
        self.assertEqual(DUBBING_PACKAGE_VERSION, package["version"])
        self.assertEqual("faithful", package["translation"]["mode"])
        self.assertFalse(package["enable_narration_cta"])
        self.assertFalse(package["enable_seamless_loop_adaptation"])
        self.assertEqual("asset-1", package["source"]["asset_id"])

    def test_legacy_seo_maps_without_inventing_branding(self):
        metadata = legacy_seo_to_publish_metadata({"title": "Title", "caption_seo": "Description", "hashtags": ["one"]})
        self.assertEqual("Title", metadata["youtube"]["title"])
        self.assertEqual(["one"], metadata["youtube"]["hashtags"])
        self.assertNotIn("pinned_comment", metadata["youtube"])

    def test_timing_qc_is_explicit(self):
        qc = record_timing_qc([{"target_duration_ms": 1000, "rendered_audio_duration_ms": 1200}])
        self.assertEqual("PASSED", qc["status"])
        self.assertEqual(200, qc["max_timing_drift_ms"])
        self.assertEqual(0, qc["segments_over_tolerance"])

    def test_adaptation_never_overwrites_faithful_translation(self):
        segment = {"source_text": "Hello world.", "translated_text": "Xin chào thế giới.", "adapted_text": "Chào cả nhà!"}
        self.assertEqual("Xin chào thế giới.", select_render_text(segment, "faithful"))
        self.assertEqual("Chào cả nhà!", select_render_text(segment, "localized_adaptation"))
        self.assertEqual("Xin chào thế giới.", segment["translated_text"])

    def test_adaptation_falls_back_to_faithful_text(self):
        segment = {"source_text": "Hello world.", "translated_text": "Xin chào thế giới."}
        self.assertEqual("Xin chào thế giới.", select_render_text(segment, "localized_adaptation"))

    def test_out_of_tolerance_is_not_reported_as_passed(self):
        qc = record_timing_qc([{'target_duration_ms':1000, 'rendered_audio_duration_ms':500}])
        self.assertNotEqual('PASSED',qc['status'])
        self.assertEqual(-500,qc['segments'][0]['timing_drift_ms'])

    def test_missing_segment_measurement_is_not_passed(self):
        qc = record_timing_qc([{'target_duration_ms':1000,'rendered_audio_duration_ms':1000}, {'target_duration_ms':2000}])
        self.assertNotEqual('PASSED',qc['status'])
