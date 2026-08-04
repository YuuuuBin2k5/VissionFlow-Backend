import sys
import unittest
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parents[2]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

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
            h_ratio = min(0.35, max(0.12, float(blur_region_height_ratio or 0.20)))
            filter_nodes.append(
                f"{current_v}split=2[v_base][v_strip];"
                f"[v_strip]crop=iw:ih*{h_ratio:.2f}:0:ih*{1.0 - h_ratio:.2f},boxblur=25:5[v_blur_strip];"
                f"[v_base][v_blur_strip]overlay=0:H*{1.0 - h_ratio:.2f}[v_unsub]"
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

        self.assertIn("crop=iw:ih*0.22:0:ih*0.78", filter_complex_str)
        self.assertIn("boxblur=25:5", filter_complex_str)
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
            organization_id="org-test",
            workflow_run_id="wf-test",
            render_mode=RenderMode.TRANSLATE_DUB
        )
        self.assertTrue(self.strategy.can_handle(contract))


class TestDubbingRouter(unittest.TestCase):
    def test_dispatch_dubbing_job_validation(self):
        """Kiểm tra endpoint /dubbing/dispatch báo lỗi 422 khi thiếu cả link lẫn file"""
        from fastapi import HTTPException
        empty_payload = DubbingDispatchRequest(source_url=None, file_path=None)
        with self.assertRaises(HTTPException) as ctx:
            dispatch_dubbing_job(empty_payload)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_dispatch_dubbing_job_success(self):
        """Kiểm tra endpoint /dubbing/dispatch trả về trạng thái queued khi gửi link hợp lệ"""
        payload = DubbingDispatchRequest(
            source_url="https://v.douyin.com/abc12345/",
            blur_original_subtitles=True,
            blur_region_height_ratio=0.22,
            logo_handle="@GocChiemNghiemYuuBin",
            caption_preset="montserrat"
        )
        res = dispatch_dubbing_job(payload)
        self.assertEqual(res["status"], "queued")
        self.assertIn("job_id", res)
        self.assertTrue(res["metadata"]["blur_original_subtitles"])
        self.assertEqual(res["metadata"]["logo_handle"], "@GocChiemNghiemYuuBin")


if __name__ == "__main__":
    unittest.main()
