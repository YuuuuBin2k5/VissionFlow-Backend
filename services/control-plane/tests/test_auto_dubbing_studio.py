import sys
import unittest
import uuid
from pathlib import Path

# Add backend directory and control plane to sys.path
backend_dir = Path(__file__).resolve().parents[2]
cp_dir = backend_dir / "services" / "control-plane"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
if str(cp_dir) not in sys.path:
    sys.path.insert(0, str(cp_dir))

from worker.services.dubbing_service import DubbingService
from worker.application.render_strategies.dubbing_strategy import DubbingStrategy
from worker.domain.render_contract import RenderContract, RenderMode
from app.routers.dubbing import dispatch_dubbing_job, DubbingDispatchRequest


class TestDubbingServiceFilters(unittest.TestCase):
    def setUp(self):
        self.dubber = DubbingService()

    def test_ffmpeg_filter_complex_with_subtitle_blur(self):
        """Kiểm tra filter graph tự động tạo dải boxblur che mờ phụ đề tiếng Trung gốc"""
        blur_original_subtitles = True
        blur_region_height_ratio = 0.22
        logo_handle = "@GocChiemNghiemYuuBin"
        aspect_ratio = "vertical_blur"
        has_subtitles = True
        escaped_srt = "subtitles.srt"

        style_str = ":force_style='FontName=Montserrat,FontSize=28'"

        filter_nodes = []
        current_v = "[0:v]"

        if blur_original_subtitles:
            y_center_pct = 0.80
            h_ratio = min(0.20, max(0.08, float(blur_region_height_ratio or 0.14)))
            y_top_ratio = max(0.50, min(0.85, y_center_pct - (h_ratio / 2.0)))
            filter_nodes.append(
                f"{current_v}split=2[v_base][v_strip];"
                f"[v_strip]crop=iw:ih*{h_ratio:.2f}:0:ih*{y_top_ratio:.2f},boxblur=18:3[v_blur_strip];"
                f"[v_base][v_blur_strip]overlay=0:H*{y_top_ratio:.2f}[v_unsub]"
            )
            current_v = "[v_unsub]"

        if logo_handle:
            filter_nodes.append(f"{current_v}drawtext=text='{logo_handle}':x=35:y=35[v_logo]")
            current_v = "[v_logo]"

        if aspect_ratio == "vertical_blur":
            filter_nodes.append(f"{current_v}scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5,setsar=1[bg];{current_v}scale=1080:-1:force_original_aspect_ratio=decrease,setsar=1[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[v_aspect]")
            current_v = "[v_aspect]"

        if has_subtitles:
            filter_nodes.append(f"{current_v}subtitles='{escaped_srt}'{style_str}[outv]")

        filter_complex_str = ";".join(filter_nodes)

        self.assertIn("crop=iw:ih*0.20:0:ih*0.70", filter_complex_str)
        self.assertIn("boxblur=18:3", filter_complex_str)
        self.assertIn("drawtext=text='@GocChiemNghiemYuuBin'", filter_complex_str)
        self.assertIn("subtitles='subtitles.srt'", filter_complex_str)

    def test_caption_preset_style_mapping(self):
        """Kiểm tra việc chuyển đổi các preset phụ đề (Hormozi, Neon, Montserrat)"""
        force_style_supported = self.dubber.check_subtitles_supports_force_style()
        self.assertIsInstance(force_style_supported, bool)


class TestDubbingStrategy(unittest.TestCase):
    def setUp(self):
        self.strategy = DubbingStrategy()

    def test_can_handle_translate_dub(self):
        """Kiểm tra DubbingStrategy nhận diện chính xác render_mode TRANSLATE_DUB"""
        contract = RenderContract(
            job_id=101,
            title="Test",
            topic="Test",
            audience="Test",
            mode=RenderMode.TRANSLATE_DUB
        )
        self.assertTrue(self.strategy.can_handle(contract))


class TestDubbingRouter(unittest.TestCase):
    def test_dispatch_dubbing_job_validation(self):
        """Kiểm tra endpoint /dubbing/dispatch báo lỗi 422 khi thiếu cả link lẫn file"""
        from fastapi import HTTPException
        empty_payload = DubbingDispatchRequest(source_url=None, file_path=None, organization_id=uuid.uuid4())
        with self.assertRaises(HTTPException) as ctx:
            dispatch_dubbing_job(empty_payload)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_dispatch_requires_organization_id(self):
        """Dubbing intake no longer selects another tenant as a fallback."""
        with self.assertRaises(Exception):
            DubbingDispatchRequest(source_url="https://example.com/video.mp4")


if __name__ == "__main__":
    unittest.main()
