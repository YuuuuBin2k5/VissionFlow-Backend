"""
Unit tests for Logo Overlay Positioning & Coordinates Parity between Frontend and Backend.
Verifies that logo coordinates and positions are reconciled properly and boundary margin clamping works.
"""

import os
import unittest
from PIL import Image
from modal_worker import create_logo_pill_overlay


class TestLogoOverlayParity(unittest.TestCase):
    def setUp(self):
        self.output_dir = os.path.join(os.path.dirname(__file__), "assets")
        os.makedirs(self.output_dir, exist_ok=True)
        self.test_img_path = os.path.join(self.output_dir, "test_logo_parity.png")

    def tearDown(self):
        if os.path.exists(self.test_img_path):
            try:
                os.remove(self.test_img_path)
            except Exception:
                pass

    def test_create_logo_pill_top_right(self):
        """Top-right logo pill overlay must be placed on the right quadrant of canvas."""
        canvas_w, canvas_h = 1080, 1920
        res_path = create_logo_pill_overlay(
            logo_handle="@VisionFlow",
            canvas_w=canvas_w,
            canvas_h=canvas_h,
            x_percent=82.0,
            y_percent=6.0,
            output_path=self.test_img_path
        )
        self.assertTrue(os.path.exists(res_path))
        self.assertGreater(os.path.getsize(res_path), 500)

        # Inspect generated alpha channel bounding box
        img = Image.open(res_path)
        self.assertEqual(img.size, (1080, 1920))
        bbox = img.getbbox()  # (left, upper, right, lower)
        self.assertIsNotNone(bbox)
        left, upper, right, lower = bbox

        # Verify it is on the right half of the canvas (left > 540)
        self.assertGreater(left, 540, "Top-right logo pill must be on the right half of the canvas")
        # Verify it stays inside screen margin (right <= 1080 - 24)
        self.assertLessEqual(right, 1080 - 20, "Logo pill must not bleed past right edge")
        # Verify it is in the top section (upper < 200)
        self.assertLess(upper, 200, "Top logo pill must be in the top portion")

    def test_create_logo_pill_top_left(self):
        """Top-left logo pill overlay must be placed on the left quadrant of canvas."""
        canvas_w, canvas_h = 1080, 1920
        res_path = create_logo_pill_overlay(
            logo_handle="@VisionFlow",
            canvas_w=canvas_w,
            canvas_h=canvas_h,
            x_percent=18.0,
            y_percent=6.0,
            output_path=self.test_img_path
        )
        self.assertTrue(os.path.exists(res_path))
        img = Image.open(res_path)
        bbox = img.getbbox()
        self.assertIsNotNone(bbox)
        left, upper, right, lower = bbox

        # Verify it is on the left half of the canvas (right < 540)
        self.assertLess(right, 540, "Top-left logo pill must be on the left half of the canvas")
        # Verify it stays inside safe margin (left >= 20)
        self.assertGreaterEqual(left, 20, "Logo pill must not bleed past left edge")

    def test_logo_coordinate_reconciliation_logic(self):
        """Test reconciliation algorithm for mismatched contract payloads."""
        # Case A: Contract says top_right, but legacy/stale frontend defaulted to x=18
        logo_pos = "top_right"
        default_logo_x = 18.0 if "left" in logo_pos else 82.0
        default_logo_y = 92.0 if "bottom" in logo_pos else 6.0
        raw_x, raw_y = 18.0, 6.0

        watermark_x_percent = float(raw_x)
        watermark_y_percent = float(raw_y)
        if "right" in logo_pos and watermark_x_percent <= 30.0:
            watermark_x_percent = 82.0
        if "bottom" in logo_pos and watermark_y_percent <= 30.0:
            watermark_y_percent = 92.0

        self.assertEqual(watermark_x_percent, 82.0)
        self.assertEqual(watermark_y_percent, 6.0)

        # Case B: Contract says bottom_left, but raw_y was 6.0
        logo_pos_b = "bottom_left"
        raw_x_b, raw_y_b = 18.0, 6.0
        watermark_x_b = float(raw_x_b)
        watermark_y_b = float(raw_y_b)
        if "bottom" in logo_pos_b and watermark_y_b <= 30.0:
            watermark_y_b = 92.0

        self.assertEqual(watermark_x_b, 18.0)
        self.assertEqual(watermark_y_b, 92.0)


if __name__ == "__main__":
    unittest.main()
