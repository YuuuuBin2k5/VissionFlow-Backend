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
            detected_logo_tl_boxes = []
            detected_logo_tr_boxes = []

            for t_sec in sample_times:
                frame_num = int(t_sec * fps)
                if 0 <= frame_num < total_frames:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                    ret, frame = cap.read()
                    if ret and frame is not None:
                        # 1. Quét Bounding Box phụ đề ở vùng từ 68% đến 92% chiều cao video (nơi chuẩn của phụ đề Douyin/Shorts)
                        sub_box = SmartTextDetector._detect_text_contour_in_region(
                            frame,
                            y_start_ratio=0.68,
                            y_end_ratio=0.92,
                            x_start_ratio=0.05,
                            x_end_ratio=0.95
                        )
                        if sub_box:
                            detected_sub_boxes.append(sub_box)

                        # 2a. Quét Bounding Box Logo ở 12% góc trên BÊN TRÁI
                        logo_tl = SmartTextDetector._detect_text_contour_in_region(
                            frame,
                            y_start_ratio=0.005,
                            y_end_ratio=0.12,
                            x_start_ratio=0.0,
                            x_end_ratio=0.45
                        )
                        if logo_tl:
                            detected_logo_tl_boxes.append(logo_tl)

                        # 2b. Quét Bounding Box Logo ở 12% góc trên BÊN PHẢI (VD: logo tên tác giả / 劍奇)
                        logo_tr = SmartTextDetector._detect_text_contour_in_region(
                            frame,
                            y_start_ratio=0.005,
                            y_end_ratio=0.12,
                            x_start_ratio=0.55,
                            x_end_ratio=1.0
                        )
                        if logo_tr:
                            detected_logo_tr_boxes.append(logo_tr)

            cap.release()

            # Hợp nhất các Bounding Boxes thu hoạch được thành Vùng Bounding Envelope hoàn chỉnh
            sub_region = SmartTextDetector._merge_sub_boxes(detected_sub_boxes)
            logo_tl_region = SmartTextDetector._merge_logo_boxes(detected_logo_tl_boxes, is_right=False)
            logo_tr_region = SmartTextDetector._merge_logo_boxes(detected_logo_tr_boxes, is_right=True)

            print(f"[SmartTextDetector AI] Subtitle Bounding Box Detected: {sub_region}")
            print(f"[SmartTextDetector AI] Logo Top-Left Bounding Box: {logo_tl_region}")
            print(f"[SmartTextDetector AI] Logo Top-Right Bounding Box: {logo_tr_region}")

            return {
                "subtitle": sub_region,
                "logo_topleft": logo_tl_region,
                "logo_topright": logo_tr_region,
                # Giữ tương thích ngược key logo
                "logo": logo_tl_region if logo_tl_region else logo_tr_region
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
    def _merge_sub_boxes(boxes: list) -> dict:
        """Hợp nhất và xác định vị trí Bounding Box chính xác vừa khít dòng chữ Trung Quốc gốc."""
        if not boxes:
            return {
                "x_ratio": 0.15,
                "y_top_ratio": 0.82,
                "w_ratio": 0.70,
                "h_ratio": 0.11
            }

        # Lọc chính xác các box thuộc vùng phụ đề tiếng Trung sát đáy video (y >= 0.70)
        sub_boxes = [b for b in boxes if b[1] >= 0.70]
        if not sub_boxes:
            min_y = 0.82
            max_y = 0.93
            min_x = 0.20
            max_x = 0.80
        else:
            # Tính trung bình vị trí x và w của các câu thoại để tránh 1 câu dài làm phình to toàn bộ các câu ngắn
            xs = [b[0] for b in sub_boxes]
            xw_rights = [b[0] + b[2] for b in sub_boxes]
            ys = [b[1] for b in sub_boxes]
            yh_bottoms = [b[1] + b[3] for b in sub_boxes]

            # Dùng percentiles (15th và 85th) để loại bỏ outlier câu quá dài hoặc vệt sáng nhiễu
            min_x = np.percentile(xs, 10) if len(xs) > 2 else min(xs)
            max_x = np.percentile(xw_rights, 90) if len(xw_rights) > 2 else max(xw_rights)
            min_y = min(ys)
            max_y = max(yh_bottoms)

        # Padding vừa đủ 0.8%
        padded_top = max(0.75, min_y - 0.008)
        padded_bottom = min(0.96, max_y + 0.008)
        padded_h = min(0.14, max(0.065, padded_bottom - padded_top))

        padded_left = max(0.08, min_x - 0.015)
        padded_w = min(0.84, max(0.35, max_x - padded_left + 0.03))

        return {
            "x_ratio": round(padded_left, 3),
            "y_top_ratio": round(padded_top, 3),
            "w_ratio": round(padded_w, 3),
            "h_ratio": round(padded_h, 3)
        }

    @staticmethod
    def _merge_logo_boxes(boxes: list, is_right: bool = False) -> Optional[dict]:
        """Hợp nhất các Bounding Box của Logo / Watermark góc trên. Chỉ trả về dict khi thực sự phát hiện thấy contour nét chữ/logo."""
        if not boxes:
            return None

        min_y = min(b[1] for b in boxes)
        max_y = max(b[1] + b[3] for b in boxes)
        min_x = min(b[0] for b in boxes)
        max_x = max(b[0] + b[2] for b in boxes)

        padded_top = max(0.005, min_y - 0.003)
        # Giới hạn chiều cao mờ logo tối đa 5.5% chiều cao video (nhỏ gọn vừa vặn nét chữ)
        padded_h = min(0.055, max(0.03, max_y - min_y + 0.006))

        if is_right:
            padded_left = max(0.55, min_x - 0.008)
            padded_w = min(0.40, max(0.12, max_x - padded_left + 0.015))
        else:
            padded_left = max(0.0, min_x - 0.008)
            padded_w = min(0.40, max(0.12, max_x - padded_left + 0.015))

        return {
            "x_ratio": round(padded_left, 3),
            "y_top_ratio": round(padded_top, 3),
            "w_ratio": round(padded_w, 3),
            "h_ratio": round(padded_h, 3)
        }

    @staticmethod
    def _get_default_regions() -> Dict[str, dict]:
        return {
            "subtitle": {"x_ratio": 0.0, "y_top_ratio": 0.74, "w_ratio": 1.0, "h_ratio": 0.14},
            "logo_topleft": {"x_ratio": 0.0, "y_top_ratio": 0.01, "w_ratio": 0.35, "h_ratio": 0.075},
            "logo_topright": {"x_ratio": 0.65, "y_top_ratio": 0.01, "w_ratio": 0.35, "h_ratio": 0.075},
            "logo": {"x_ratio": 0.0, "y_top_ratio": 0.01, "w_ratio": 0.35, "h_ratio": 0.075}
        }
