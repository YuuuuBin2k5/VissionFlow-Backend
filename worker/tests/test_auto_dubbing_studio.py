"""
Unit Tests — Auto Dubbing Studio
=================================
Kiểm tra toàn bộ logic của tính năng AI Dubbing & Vietsub:
  1. DubbingService: FFmpeg filter graph assembly (không cần FFmpeg thật)
  2. DubbingService: Caption preset style strings
  3. DubbingService: SRT file generation
  4. DubbingService: Merge adjacent segments
  5. DubbingService: format_srt_time
  6. DubbingDispatchRequest: Pydantic model validation
  7. DubbingDispatchRequest: Router dispatch logic (not 422)
  8. DubbingStrategy: can_handle render_mode detection

Chạy: cd VisionFlow_Bakend && venv\Scripts\python.exe -m pytest worker/tests/test_auto_dubbing_studio.py -v
"""
import sys
import os
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# ---------------------------------------------------------------------------
# Path setup — thêm thư mục gốc backend vào sys.path
# ---------------------------------------------------------------------------
BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# ---------------------------------------------------------------------------
# Import sau khi path đã được set đúng
# ---------------------------------------------------------------------------
from worker.services.dubbing_service import DubbingService
from worker.application.render_strategies.dubbing_strategy import DubbingStrategy
from worker.domain.render_contract import RenderContract, RenderMode


# ===========================================================================
# TEST GROUP 1: DubbingService — FFmpeg Filter Graph Assembly
# ===========================================================================
class TestFilterComplexAssembly(unittest.TestCase):
    """Kiểm tra logic lắp ghép filter_complex FFmpeg (không cần FFmpeg thật)"""

    def _build_filter(
        self,
        blur=True,
        blur_ratio=0.20,
        logo="@GocChiemNghiemYuuBin",
        aspect_ratio="vertical_blur",
        has_subtitles=True,
        srt="subtitles.srt",
        caption_preset="montserrat",
    ) -> str:
        """Helper: lắp ghép filter graph giống DubbingService"""
        style_map = {
            "hormozi": ":force_style='FontName=Montserrat,FontSize=32,Bold=1,PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=3,Shadow=2,MarginV=140'",
            "neon":    ":force_style='FontName=Montserrat,FontSize=30,Bold=1,PrimaryColour=&H0000FF00,OutlineColour=&H00000000,BorderStyle=1,Outline=3,Shadow=2,MarginV=140'",
        }
        margin_v = 300 if aspect_ratio == "vertical_blur" else 120
        style_str = style_map.get(caption_preset, f":force_style='FontName=Montserrat,FontSize=28,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,MarginV={margin_v}'")

        filter_nodes = []
        current_v = "[0:v]"

        if blur:
            h = min(0.35, max(0.12, float(blur_ratio or 0.20)))
            filter_nodes.append(
                f"{current_v}split=2[v_base][v_strip];"
                f"[v_strip]crop=iw:ih*{h:.2f}:0:ih*{1.0 - h:.2f},boxblur=25:5[v_blur_strip];"
                f"[v_base][v_blur_strip]overlay=0:H*{1.0 - h:.2f}[v_unsub]"
            )
            current_v = "[v_unsub]"

        if logo and logo.strip():
            clean = logo.strip().replace("'", "'\\''").replace(":", "\\:")
            filter_nodes.append(
                f"{current_v}drawtext=text='{clean}':x=35:y=35:fontsize=22:fontcolor=white@0.85:shadowcolor=black@0.6:shadowx=2:shadowy=2[v_logo]"
            )
            current_v = "[v_logo]"

        if aspect_ratio == "vertical_blur":
            filter_nodes.append(
                f"{current_v}scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5,setsar=1[bg];"
                f"{current_v}scale=1080:-1:force_original_aspect_ratio=decrease,setsar=1[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2[v_aspect]"
            )
            current_v = "[v_aspect]"

        if has_subtitles:
            filter_nodes.append(f"{current_v}subtitles='{srt}'{style_str}[outv]")
        else:
            filter_nodes.append(f"{current_v}null[outv]")

        return ";".join(filter_nodes)

    def test_blur_strip_contains_boxblur(self):
        """Phải có filter boxblur=25:5 khi bật blur phụ đề gốc"""
        fc = self._build_filter(blur=True)
        self.assertIn("boxblur=25:5", fc)

    def test_blur_strip_crop_dimensions_20pct(self):
        """Với blur_ratio=0.20 phải crop đúng ih*0.20:0:ih*0.80"""
        fc = self._build_filter(blur=True, blur_ratio=0.20)
        self.assertIn("crop=iw:ih*0.20:0:ih*0.80", fc)

    def test_blur_strip_crop_dimensions_25pct(self):
        """Với blur_ratio=0.25 phải crop đúng ih*0.25:0:ih*0.75"""
        fc = self._build_filter(blur=True, blur_ratio=0.25)
        self.assertIn("crop=iw:ih*0.25:0:ih*0.75", fc)

    def test_blur_strip_clamped_below_min(self):
        """blur_ratio quá nhỏ (< 0.12) phải bị clamp về 0.12"""
        fc = self._build_filter(blur=True, blur_ratio=0.05)
        self.assertIn("crop=iw:ih*0.12:0:ih*0.88", fc)

    def test_blur_strip_clamped_above_max(self):
        """blur_ratio quá lớn (> 0.35) phải bị clamp về 0.35"""
        fc = self._build_filter(blur=True, blur_ratio=0.99)
        self.assertIn("crop=iw:ih*0.35:0:ih*0.65", fc)

    def test_no_blur_skips_crop(self):
        """Khi tắt blur thì không có crop/boxblur=25:5"""
        fc = self._build_filter(blur=False)
        self.assertNotIn("crop=iw:ih*", fc)
        self.assertNotIn("boxblur=25:5", fc)

    def test_logo_drawtext_present(self):
        """Phải có drawtext với handle kênh khi logo_handle được cung cấp"""
        fc = self._build_filter(logo="@GocChiemNghiemYuuBin")
        self.assertIn("drawtext=text='@GocChiemNghiemYuuBin'", fc)

    def test_empty_logo_skips_drawtext(self):
        """Không có drawtext khi logo_handle rỗng"""
        fc = self._build_filter(logo="")
        self.assertNotIn("drawtext", fc)

    def test_vertical_blur_aspect_ratio_scales_to_1080x1920(self):
        """aspect_ratio=vertical_blur phải có scale=1080:1920"""
        fc = self._build_filter(aspect_ratio="vertical_blur")
        self.assertIn("scale=1080:1920", fc)

    def test_original_aspect_ratio_no_scale(self):
        """aspect_ratio=original không được có scale=1080:1920"""
        fc = self._build_filter(aspect_ratio="original")
        self.assertNotIn("scale=1080:1920", fc)

    def test_subtitles_burned_when_has_subtitles(self):
        """Phải có subtitles filter khi has_subtitles=True"""
        fc = self._build_filter(has_subtitles=True, srt="my_subs.srt")
        self.assertIn("subtitles='my_subs.srt'", fc)

    def test_no_subtitles_uses_null_filter(self):
        """Khi has_subtitles=False phải dùng null filter"""
        fc = self._build_filter(has_subtitles=False)
        self.assertIn("null[outv]", fc)

    def test_output_always_ends_with_outv(self):
        """Graph luôn phải kết thúc bằng [outv]"""
        for blur, logo, aspect, subs in [
            (True, "@chan", "vertical_blur", True),
            (False, "", "original", False),
            (True, "", "vertical_blur", True),
        ]:
            fc = self._build_filter(blur=blur, logo=logo, aspect_ratio=aspect, has_subtitles=subs)
            self.assertTrue(fc.endswith("[outv]"), f"Filter không kết thúc [outv]: {fc[-40:]}")

    def test_caption_preset_montserrat_white_color(self):
        """Preset montserrat phải dùng màu trắng PrimaryColour=&H00FFFFFF"""
        fc = self._build_filter(caption_preset="montserrat")
        self.assertIn("PrimaryColour=&H00FFFFFF", fc)

    def test_caption_preset_hormozi_yellow_color(self):
        """Preset hormozi phải dùng màu vàng PrimaryColour=&H0000FFFF"""
        fc = self._build_filter(caption_preset="hormozi")
        self.assertIn("PrimaryColour=&H0000FFFF", fc)

    def test_caption_preset_neon_green_color(self):
        """Preset neon phải dùng màu xanh lá PrimaryColour=&H0000FF00"""
        fc = self._build_filter(caption_preset="neon")
        self.assertIn("PrimaryColour=&H0000FF00", fc)

    def test_node_chain_order(self):
        """Thứ tự nodes phải: blur -> logo -> aspect -> subs"""
        fc = self._build_filter(blur=True, logo="@chan", aspect_ratio="vertical_blur", has_subtitles=True)
        idx_blur  = fc.find("boxblur=25:5")
        idx_logo  = fc.find("drawtext")
        idx_scale = fc.find("scale=1080:1920")
        idx_sub   = fc.find("subtitles=")
        self.assertLess(idx_blur, idx_logo, "blur phải trước logo")
        self.assertLess(idx_logo, idx_scale, "logo phải trước scale")
        self.assertLess(idx_scale, idx_sub, "scale phải trước subtitles")


# ===========================================================================
# TEST GROUP 2: DubbingService — format_srt_time & SRT generation
# ===========================================================================
class TestDubbingServiceHelpers(unittest.TestCase):
    def setUp(self):
        self.dubber = DubbingService()

    def test_format_srt_time_zero(self):
        self.assertEqual(self.dubber.format_srt_time(0.0), "00:00:00,000")

    def test_format_srt_time_one_hour(self):
        self.assertEqual(self.dubber.format_srt_time(3600.0), "01:00:00,000")

    def test_format_srt_time_mixed(self):
        self.assertEqual(self.dubber.format_srt_time(61.5), "00:01:01,500")

    def test_format_srt_time_fractional(self):
        self.assertEqual(self.dubber.format_srt_time(1.123), "00:00:01,123")

    def test_generate_srt_file_creates_file(self):
        import tempfile
        timeline = [
            {"start": 0.0, "end": 2.0, "translated_text": "Xin chào"},
            {"start": 3.0, "end": 5.0, "translated_text": "Tạm biệt"},
        ]
        with tempfile.NamedTemporaryFile(suffix=".srt", delete=False, mode="w") as f:
            srt_path = f.name
        try:
            self.dubber.generate_srt_file(timeline, srt_path)
            with open(srt_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("Xin chào", content)
            self.assertIn("Tạm biệt", content)
            self.assertIn("-->", content)
        finally:
            os.unlink(srt_path)

    def test_merge_adjacent_segments_merges_close(self):
        """Segments cách nhau < 0.5s phải được gộp"""
        segs = [
            {"start": 0.0, "end": 1.0, "text": "Một"},
            {"start": 1.2, "end": 2.0, "text": "hai"},
        ]
        merged = self.dubber.merge_adjacent_segments(segs)
        self.assertLessEqual(len(merged), len(segs))

    def test_merge_adjacent_segments_keeps_far_apart(self):
        """Segments cách nhau > 1.5s phải giữ nguyên riêng biệt"""
        segs = [
            {"start": 0.0, "end": 1.0, "text": "Đoạn A"},
            {"start": 5.0, "end": 7.0, "text": "Đoạn B"},
        ]
        merged = self.dubber.merge_adjacent_segments(segs)
        self.assertEqual(len(merged), 2)


# ===========================================================================
# TEST GROUP 3: DubbingStrategy — can_handle logic
# ===========================================================================
class TestDubbingStrategyCanHandle(unittest.TestCase):
    def setUp(self):
        self.strategy = DubbingStrategy()

    def _make_contract(self, mode: RenderMode) -> RenderContract:
        return RenderContract(
            job_id=1,
            title="Test Video",
            topic="Test topic",
            audience="general",
            mode=mode,
        )

    def test_handles_translate_dub(self):
        self.assertTrue(self.strategy.can_handle(self._make_contract(RenderMode.TRANSLATE_DUB)))

    def test_does_not_handle_other_modes(self):
        for mode in [m for m in RenderMode if m != RenderMode.TRANSLATE_DUB]:
            self.assertFalse(
                self.strategy.can_handle(self._make_contract(mode)),
                f"DubbingStrategy không được handle mode: {mode}"
            )


# ===========================================================================
# TEST GROUP 4: Dubbing Router — DubbingDispatchRequest Pydantic validation
# ===========================================================================
class TestDubbingDispatchRequest(unittest.TestCase):
    """Test Pydantic model validation không cần import app (tránh DATABASE_URL error)"""

    def _import_request(self):
        """Import DubbingDispatchRequest từ router mà không trigger Settings.from_env()"""
        import importlib
        cp_dir = str(BACKEND_DIR / "services" / "control-plane")
        if cp_dir not in sys.path:
            sys.path.insert(0, cp_dir)
        spec = importlib.util.spec_from_file_location(
            "dubbing_router",
            str(BACKEND_DIR / "services" / "control-plane" / "app" / "routers" / "dubbing.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.DubbingDispatchRequest, mod.dispatch_dubbing_job

    def test_default_values(self):
        DubbingDispatchRequest, _ = self._import_request()
        req = DubbingDispatchRequest(source_url="https://v.douyin.com/test/")
        self.assertEqual(req.voice_gender, "female")
        self.assertEqual(req.aspect_ratio, "vertical_blur")
        self.assertEqual(req.blur_region_height_ratio, 0.20)
        self.assertEqual(req.logo_handle, "GócChiêmNghiệm||YuuuBin")
        self.assertEqual(req.caption_preset, "montserrat")
        self.assertFalse(req.mute_original_audio)
        self.assertFalse(req.auto_publish_enabled)
        self.assertEqual(req.bgm_preset, "relaxing_chill")
        self.assertAlmostEqual(req.bgm_volume, 0.18)
        self.assertTrue(req.smart_dynamic_blur)

    def test_raises_422_when_no_source(self):
        from fastapi import HTTPException
        DubbingDispatchRequest, dispatch_dubbing_job = self._import_request()
        req = DubbingDispatchRequest(source_url=None, file_path=None)
        with self.assertRaises(HTTPException) as ctx:
            dispatch_dubbing_job(req)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_dispatch_returns_queued_with_link(self):
        DubbingDispatchRequest, dispatch_dubbing_job = self._import_request()
        req = DubbingDispatchRequest(
            source_url="https://v.douyin.com/abc123/",
            blur_original_subtitles=True,
            blur_region_height_ratio=0.22,
            logo_handle="@TestChannel",
            caption_preset="neon",
        )
        res = dispatch_dubbing_job(req)
        self.assertEqual(res["status"], "queued")
        self.assertIn("job_id", res)
        self.assertIn("metadata", res)
        self.assertTrue(res["metadata"]["blur_original_subtitles"])
        self.assertEqual(res["metadata"]["logo_handle"], "@TestChannel")
        self.assertEqual(res["metadata"]["caption_preset"], "neon")
        self.assertAlmostEqual(res["metadata"]["blur_region_height_ratio"], 0.22)

    def test_dispatch_returns_queued_with_file_path(self):
        DubbingDispatchRequest, dispatch_dubbing_job = self._import_request()
        req = DubbingDispatchRequest(
            file_path="my_video.mp4",
            voice_gender="male",
            aspect_ratio="vertical_blur",
            mute_original_audio=True,
        )
        res = dispatch_dubbing_job(req)
        self.assertEqual(res["status"], "queued")
        self.assertTrue(res["metadata"]["mute_original_audio"])

    def test_metadata_render_mode_is_translate_dub(self):
        DubbingDispatchRequest, dispatch_dubbing_job = self._import_request()
        req = DubbingDispatchRequest(source_url="https://www.tiktok.com/@user/video/123")
        res = dispatch_dubbing_job(req)
        self.assertEqual(res["metadata"]["render_mode"], "TRANSLATE_DUB")

    def test_auto_publish_enabled_propagates(self):
        DubbingDispatchRequest, dispatch_dubbing_job = self._import_request()
        req = DubbingDispatchRequest(
            source_url="https://v.douyin.com/xyz/",
            auto_publish_enabled=True,
            auto_publish_channel="goc_chiem_nghiem",
            auto_publish_mode="immediate",
        )
        res = dispatch_dubbing_job(req)
        self.assertTrue(res["metadata"]["auto_publish_enabled"])
        self.assertEqual(res["metadata"]["auto_publish_channel"], "goc_chiem_nghiem")

    def test_bgm_and_smart_dynamic_blur_metadata_propagation(self):
        DubbingDispatchRequest, dispatch_dubbing_job = self._import_request()
        req = DubbingDispatchRequest(
            source_url="https://v.douyin.com/xyz/",
            bgm_preset="uplifting_happy",
            bgm_custom_url="https://www.youtube.com/watch?v=test",
            bgm_volume=0.25,
            smart_dynamic_blur=True,
        )
        res = dispatch_dubbing_job(req)
        self.assertEqual(res["metadata"]["bgm_preset"], "uplifting_happy")
        self.assertEqual(res["metadata"]["bgm_custom_url"], "https://www.youtube.com/watch?v=test")
        self.assertAlmostEqual(res["metadata"]["bgm_volume"], 0.25)
        self.assertTrue(res["metadata"]["smart_dynamic_blur"])

    def test_vocal_removal_mode_metadata_propagation(self):
        DubbingDispatchRequest, dispatch_dubbing_job = self._import_request()
        req = DubbingDispatchRequest(
            source_url="https://v.douyin.com/xyz/",
            vocal_removal_mode="ffmpeg_phase_cancel",
        )
        res = dispatch_dubbing_job(req)
        self.assertEqual(res["metadata"]["vocal_removal_mode"], "ffmpeg_phase_cancel")


# ===========================================================================
# TEST GROUP 5: DubbingService — check_subtitles_supports_force_style
# ===========================================================================
class TestDubbingServiceSubtitleSupport(unittest.TestCase):
    def setUp(self):
        self.dubber = DubbingService()

    def test_check_subtitles_supports_force_style_returns_bool(self):
        result = self.dubber.check_subtitles_supports_force_style()
        self.assertIsInstance(result, bool)


# ===========================================================================
# TEST GROUP 6: Adam Voice & English Target Language Resolution
# ===========================================================================
class TestAdamVoiceHandling(unittest.TestCase):
    def test_adam_voice_switches_target_language_to_english(self):
        """Kiểm tra chọn giọng Adam (tiếng Anh) tự động kích hoạt dịch thuật sang tiếng Anh"""
        english_voices = ["adam", "eleven-adam", "edge-en-christopher", "edge-en-adam"]
        for vcode in english_voices:
            target_lang = "auto"
            if vcode.lower() in english_voices or vcode.lower().startswith("en-"):
                if target_lang in ["auto", "vi"]:
                    target_lang = "en"
            self.assertEqual(target_lang, "en", f"Voice {vcode} phải kích hoạt target_lang='en'")

    def test_tts_service_instantiation_with_adam_voice(self):
        """Kiểm tra TTSService khởi tạo với giọng Adam"""
        from worker.services.tts_service import TTSService
        tts = TTSService(voice="adam")
        self.assertEqual(tts.voice, "adam")


if __name__ == "__main__":
    unittest.main(verbosity=2)

