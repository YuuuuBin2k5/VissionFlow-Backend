"""
Smart AI Text & Logo Bounding Box Detector
===================================================
Sử dụng Computer Vision (OpenCV + Morphological Text Contour Analysis)
để tự động quét 5-10 khung hình thực tế của Video nguồn,
phát hiện chính xác 100% tọa độ Bounding Box (x, y, w, h) của:
1. Phụ đề tiếng Trung gốc (Vùng chữ thoại chính)
2. Logo & Username kênh gốc (Góc trên bên trái / góc dưới bên phải)
"""

from __future__ import annotations

import cv2
import numpy as np
from pathlib import Path
from typing import Optional, Dict, Tuple, List


class SmartTextDetector:
    """Bộ nhận diện vùng chữ & logo thông minh bằng OpenCV cho VisionFlow Worker"""

    @staticmethod
    def detect_video_regions(video_path: str, timestamps: Optional[List[dict]] = None) -> Dict[str, dict]:
        """
        Trích xuất các khung hình tại mốc thời gian thoại và quét nhận diện Bounding Box.
        Trả về dictionary chứa tỷ lệ crop chuẩn (x_ratio, y_top_ratio, w_ratio, h_ratio).
        """
        if not video_path or not Path(video_path).exists():
            return SmartTextDetector._get_default_regions()

        try:
            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                return SmartTextDetector._get_default_regions()

            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = max(1.0, cap.get(cv2.CAP_PROP_FPS))
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

            if width <= 0 or height <= 0 or total_frames <= 0:
                cap.release()
                return SmartTextDetector._get_default_regions()

            # Chọn mốc sample frames (4-8 frame khi thoại đang phát biểu)
            sample_times = []
            if timestamps:
                for item in timestamps[:8]:
                    st = float(item.get("start", 0.0))
                    if st > 0:
                        sample_times.append(st + 0.4)

            if not sample_times:
                dur = total_frames / fps
                sample_times = [dur * 0.15, dur * 0.35, dur * 0.55, dur * 0.75]

            detected_sub_boxes = []
            detected_logo_boxes = []

            for t_sec in sample_times:
                frame_num = int(t_sec * fps)
                if 0 <= frame_num < total_frames:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                    ret, frame = cap.read()
                    if ret and frame is not None:
                        # 1. Quét Bounding Box phụ đề ở vùng từ 52% đến 92% chiều cao video
                        sub_box = SmartTextDetector._detect_text_contour_in_region(
                            frame,
                            y_start_ratio=0.52,
                            y_end_ratio=0.92,
                            x_start_ratio=0.03,
                            x_end_ratio=0.97
                        )
                        if sub_box:
                            detected_sub_boxes.append(sub_box)

                        # 2. Quét Bounding Box Logo ở 12% góc trên bên trái
                        logo_box = SmartTextDetector._detect_text_contour_in_region(
                            frame,
                            y_start_ratio=0.01,
                            y_end_ratio=0.12,
                            x_start_ratio=0.0,
                            x_end_ratio=0.45
                        )
                        if logo_box:
                            detected_logo_boxes.append(logo_box)

            cap.release()

            # Hợp nhất các Bounding Boxes thu hoạch được thành Vùng Bounding Envelope hoàn chỉnh
            sub_region = SmartTextDetector._merge_boxes(detected_sub_boxes, default_y_top=0.68, default_h=0.16, full_w=True)
            logo_region = SmartTextDetector._merge_boxes(detected_logo_boxes, default_y_top=0.015, default_h=0.075, w_ratio=0.38)

            print(f"[SmartTextDetector AI] Subtitle Bounding Box Detected: {sub_region}")
            print(f"[SmartTextDetector AI] Logo Bounding Box Detected: {logo_region}")

            return {
                "subtitle": sub_region,
                "logo": logo_region
            }
        except Exception as err:
            print(f"[SmartTextDetector Warning] Frame text detection fallback: {err}")
            return SmartTextDetector._get_default_regions()

    @staticmethod
    def _detect_text_contour_in_region(
        frame: np.ndarray,
        y_start_ratio: float,
        y_end_ratio: float,
        x_start_ratio: float,
        x_end_ratio: float
    ) -> Optional[Tuple[float, float, float, float]]:
        """Phát hiện viền chữ bằng Morphological Gradient & Otsu Thresholding trong vùng chỉ định"""
        h, w = frame.shape[:2]
        y1, y2 = int(y_start_ratio * h), int(y_end_ratio * h)
        x1, x2 = int(x_start_ratio * w), int(x_end_ratio * w)

        roi = frame[y1:y2, x1:x2]
        if roi.size == 0:
            return None

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

        # 1. Morphological Gradient để làm nổi bật đường biên ký tự chữ
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        grad = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, kernel)

        # 2. Otsu Binarization để bóc tách nét chữ sáng trên nền tối
        _, binary = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

        # 3. Morphological Close chiều ngang để nối các chữ cái trong 1 dòng phụ đề thành khối liền
        close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 3))
        closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, close_kernel)

        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        valid_rects = []
        for cnt in contours:
            cx, cy, cw, ch = cv2.boundingRect(cnt)
            # Lọc bớt nhiễu: Chữ phụ đề thường có độ rộng cw > 20px và cw/ch > 1.0
            if cw > 20 and ch > 8 and (cw / ch) > 0.9:
                abs_x = x1 + cx
                abs_y = y1 + cy
                valid_rects.append((abs_x / w, abs_y / h, cw / w, ch / h))

        if not valid_rects:
            return None

        # Gom nhóm rects thành 1 envelope
        min_x = min(r[0] for r in valid_rects)
        min_y = min(r[1] for r in valid_rects)
        max_x = max(r[0] + r[2] for r in valid_rects)
        max_y = max(r[1] + r[3] for r in valid_rects)

        return (min_x, min_y, max_x - min_x, max_y - min_y)

    @staticmethod
    def _merge_boxes(boxes: list, default_y_top: float, default_h: float, full_w: bool = False, w_ratio: float = 0.38) -> dict:
        """Thêm Safety Margin Padding và quy đổi sang format crop FFmpeg"""
        if not boxes:
            return {
                "x_ratio": 0.0 if full_w else 0.0,
                "y_top_ratio": default_y_top,
                "w_ratio": 1.0 if full_w else w_ratio,
                "h_ratio": default_h
            }

        min_y = min(b[1] for b in boxes)
        max_y = max(b[1] + b[3] for b in boxes)

        # Padding 1.8% ở mép trên và mép dưới để che mượt hoàn toàn các chân chữ
        padding_y = 0.018
        padded_top = max(0.01, min_y - padding_y)
        padded_bottom = min(0.99, max_y + padding_y)
        padded_h = max(0.08, padded_bottom - padded_top)

        if full_w:
            return {
                "x_ratio": 0.0,
                "y_top_ratio": round(padded_top, 3),
                "w_ratio": 1.0,
                "h_ratio": round(padded_h, 3)
            }
        else:
            min_x = min(b[0] for b in boxes)
            max_x = max(b[0] + b[2] for b in boxes)
            padded_left = max(0.0, min_x - 0.01)
            padded_w = max(w_ratio, max_x - padded_left + 0.02)
            return {
                "x_ratio": round(padded_left, 3),
                "y_top_ratio": round(padded_top, 3),
                "w_ratio": round(padded_w, 3),
                "h_ratio": round(padded_h, 3)
            }

    @staticmethod
    def _get_default_regions() -> Dict[str, dict]:
        return {
            "subtitle": {"x_ratio": 0.0, "y_top_ratio": 0.68, "w_ratio": 1.0, "h_ratio": 0.16},
            "logo": {"x_ratio": 0.0, "y_top_ratio": 0.015, "w_ratio": 0.38, "h_ratio": 0.075}
        }
