import os
import random
from pathlib import Path
import re
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from worker.config import ASSETS_DIR, FONTS_DIR

class SubtitleRenderer:
    def __init__(self):
        self.font_path = self._get_best_font()

    def _get_best_font(self) -> str:
        """Lấy font chữ việt hóa tốt nhất có sẵn trên hệ thống Windows hoặc thư mục shared"""
        custom_font = FONTS_DIR / "Montserrat-ExtraBold.ttf"
        if custom_font.exists():
            return str(custom_font)

        workspace_root = Path(__file__).resolve().parent.parent.parent
        alt_font = workspace_root / "AgentTiktok" / "shared" / "fonts" / "Montserrat-ExtraBold.ttf"
        if alt_font.exists():
            return str(alt_font)

        windows_fonts = [
            "C:\\Windows\\Fonts\\Impact.ttf",
            "C:\\Windows\\Fonts\\arialbd.ttf",
            "C:\\Windows\\Fonts\\tahomabd.ttf",
            "C:\\Windows\\Fonts\\segoeuib.ttf"
        ]
        for font in windows_fonts:
            if os.path.exists(font):
                return font
        return "Arial"

    def _is_keyword(self, word: str) -> bool:
        color = self._get_semantic_color(word, None)
        return color is not None

    def group_words_into_chunks(self, word_timestamps: list, max_words: int = 4, max_gap_ms: int = 500) -> list:
        if not word_timestamps:
            return []

        is_sentence_fallback = any(" " in item["word"] for item in word_timestamps)
        if is_sentence_fallback:
            chunks = []
            for item in word_timestamps:
                words = item["word"].split()
                if not words:
                    continue
                start_time = item["start_ms"] / 1000.0
                end_time = item["end_ms"] / 1000.0
                duration = end_time - start_time

                sub_groups = [words[i:i + max_words] for i in range(0, len(words), max_words)]
                curr_start = start_time
                for grp in sub_groups:
                    grp_dur = duration * (len(grp) / len(words))
                    grp_end = curr_start + grp_dur
                    word_items = []
                    word_dur = grp_dur / len(grp)
                    w_start = curr_start
                    for w in grp:
                        word_items.append({
                            "word": w,
                            "start_ms": int(w_start * 1000),
                            "end_ms": int((w_start + word_dur) * 1000)
                        })
                        w_start += word_dur
                    chunks.append(word_items)
                    curr_start = grp_end
            return chunks

        chunks = []
        current_chunk = []
        for item in word_timestamps:
            if not current_chunk:
                current_chunk.append(item)
            else:
                gap = item["start_ms"] - current_chunk[-1]["end_ms"]
                if len(current_chunk) >= max_words or gap > max_gap_ms:
                    chunks.append(current_chunk)
                    current_chunk = [item]
                else:
                    current_chunk.append(item)
        if current_chunk:
            chunks.append(current_chunk)
        return chunks

    def wrap_text(self, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list:
        words = text.split()
        lines = []
        current_line = []

        # Test drawing context
        dummy_img = Image.new("RGBA", (1, 1))
        draw = ImageDraw.Draw(dummy_img)

        for word in words:
            test_line = " ".join(current_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=font)
            width = bbox[2] - bbox[0]
            if width <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(" ".join(current_line))
                current_line = [word]
        if current_line:
            lines.append(" ".join(current_line))
        return lines

    def _fit_font(self, text: str, max_width: int, max_lines: int, start_size: int, min_size: int = 24) -> tuple:
        size = start_size
        dummy_img = Image.new("RGBA", (1, 1))
        draw = ImageDraw.Draw(dummy_img)
        while size >= min_size:
            try:
                font = ImageFont.truetype(self.font_path, size)
            except Exception:
                font = ImageFont.load_default()
                return font, [text]
            lines = self.wrap_text(text, font, max_width)
            if len(lines) <= max_lines:
                return font, lines
            size -= 4
        try:
            font = ImageFont.truetype(self.font_path, min_size)
        except Exception:
            font = ImageFont.load_default()
        return font, self.wrap_text(text, font, max_width)

    def _subtitle_style(self, style_name: str, accent: str) -> dict:
        styles = {
            "moneyprinter_vietsub": {
                "fill": "white",
                "stroke": "black",
                "stroke_width": 5,
                "box": (0, 0, 0, 150),
                "box_outline": (255, 255, 255, 42),
                "accent": accent,
                "font_size": 56,
                "highlight_mode": "word",
            },
            "clean_authority": {
                "fill": "white",
                "stroke": "#07111f",
                "stroke_width": 5,
                "box": (7, 17, 31, 190),
                "box_outline": (255, 255, 255, 42),
                "accent": accent,
                "font_size": 54,
            },
            "news_explainer": {
                "fill": "#0f172a",
                "stroke": "white",
                "stroke_width": 3,
                "box": (250, 250, 250, 230),
                "box_outline": (0, 0, 0, 210),
                "accent": accent,
                "font_size": 52,
            },
            "warm_story": {
                "fill": "#fff7ed",
                "stroke": "#2f1d0b",
                "stroke_width": 4,
                "box": (54, 36, 20, 170),
                "box_outline": (245, 158, 11, 120),
                "accent": accent,
                "font_size": 52,
            },
            "punchy": {
                "fill": "white",
                "stroke": "black",
                "stroke_width": 6,
                "box": (0, 0, 0, 90),
                "box_outline": (255, 61, 242, 190),
                "accent": accent,
                "font_size": 58,
            },
            "bold_punchy": {
                "fill": "white",
                "stroke": "black",
                "stroke_width": 6,
                "box": (0, 0, 0, 92),
                "box_outline": (255, 61, 242, 190),
                "accent": accent,
                "font_size": 60,
                "highlight_mode": "word",
            },
            "word_highlight": {
                "fill": "white",
                "stroke": "#07111f",
                "stroke_width": 5,
                "box": (7, 17, 31, 190),
                "box_outline": (255, 255, 255, 46),
                "accent": accent,
                "font_size": 56,
                "highlight_mode": "word",
            },
            "karaoke_sweep": {
                "fill": "white",
                "stroke": "black",
                "stroke_width": 5,
                "box": (0, 0, 0, 98),
                "box_outline": (255, 255, 255, 52),
                "accent": accent,
                "font_size": 56,
                "highlight_mode": "sweep",
            },
            "sticker_pop": {
                "fill": "#101010",
                "stroke": "white",
                "stroke_width": 2,
                "box": (255, 247, 168, 240),
                "box_outline": (17, 17, 17, 255),
                "accent": accent,
                "font_size": 56,
                "highlight_mode": "word",
            },
            "lyric_glass": {
                "fill": "white",
                "stroke": "#07111f",
                "stroke_width": 4,
                "box": (255, 255, 255, 38),
                "box_outline": (255, 255, 255, 90),
                "accent": accent,
                "font_size": 54,
                "highlight_mode": "sweep",
            },
        }
        return styles.get(style_name, styles["punchy"])

    def _apply_default_vietsub_policy(self, visual_style_plan: dict | None) -> dict:
        plan = dict(visual_style_plan or {})
        plan.setdefault("subtitle_enabled", True)
        plan.setdefault("subtitle_language", "vi")
        plan.setdefault("subtitle_style", "moneyprinter_vietsub")
        plan.setdefault("caption_style", plan.get("subtitle_style", "moneyprinter_vietsub"))
        plan.setdefault("caption_max_words", 5)
        plan.setdefault("caption_max_gap_ms", 520)
        plan.setdefault("safe_zone", {"x": 96, "top": 180, "bottom": 380})
        return plan

    def _get_semantic_color(self, word: str, fallback_color: str) -> str:
        clean_word = word.lower().strip(".,!?\"'()[]{}<>:;")

        positive_keywords = [
            "giàu", "thành công", "tiền", "bí mật", "bứt phá", "tư duy", "làm chủ",
            "học", "hiểu", "đúng", "vinh quang", "dũng cảm", "chiến thắng",
            "sáng tạo", "bước tiếp", "giải pháp", "khôn ngoan", "tự do",
            "hạnh phúc", "thông thái", "may mắn", "năng lượng", "triết lý", "sống"
        ]

        negative_keywords = [
            "sai lầm", "thất bại", "nghèo", "chết", "đừng", "từ bỏ", "cấm",
            "bi kịch", "bỏ bê", "hối hận", "đáy vực", "đổ vỡ", "bất lực",
            "giông bão", "đơn độc", "lo lắng", "trầy xước", "bóng tối",
            "sợ hãi", "lừa dối", "sai", "nguy hiểm", "cảnh báo"
        ]

        for pk in positive_keywords:
            if pk in clean_word:
                return "#00FF66" if len(clean_word) % 2 == 0 else "#FFDE4D"

        for nk in negative_keywords:
            if nk in clean_word:
                return "#FF3B30"

        return fallback_color

    def _draw_line_with_highlight(self, draw: ImageDraw.ImageDraw, line: str, x: int, y: int, font: ImageFont.FreeTypeFont, style: dict):
        words = line.split()
        has_semantic_word = False
        for word in words:
            sem_color = self._get_semantic_color(word, None)
            if sem_color is not None:
                has_semantic_word = True
                break

        target_index = next((idx for idx, word in enumerate(words) if len(word.strip(".,!?")) >= 4), 0) if not has_semantic_word else -1

        cursor_x = x
        for idx, word in enumerate(words):
            token = word + (" " if idx < len(words) - 1 else "")
            sem_color = self._get_semantic_color(word, None)
            if sem_color is not None:
                fill = sem_color
            elif idx == target_index:
                fill = style.get("accent") or "#FFDE4D"
            else:
                fill = style.get("fill") or "white"

            draw.text(
                (cursor_x, y),
                token,
                font=font,
                fill=fill,
                stroke_width=style["stroke_width"],
                stroke_fill=style["stroke"],
            )
            bbox = draw.textbbox((0, 0), token, font=font)
            cursor_x += bbox[2] - bbox[0]

    def _draw_text_panel(self, draw: ImageDraw.ImageDraw, lines: list, font: ImageFont.FreeTypeFont, box: tuple, style: dict, align: str = "center"):
        x1, y1, x2, y2 = box
        if style.get("box"):
            draw.rounded_rectangle(box, radius=28, fill=style["box"], outline=style.get("box_outline"), width=2)
            accent = style.get("accent")
            if accent:
                try:
                    draw.rounded_rectangle((x1, y1, x1 + 14, y2), radius=7, fill=accent)
                except Exception:
                    pass

        line_heights = []
        line_widths = []
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            line_widths.append(bbox[2] - bbox[0])
            line_heights.append(bbox[3] - bbox[1])
        line_spacing = 14
        total_height = sum(line_heights) + max(0, len(lines) - 1) * line_spacing
        y = y1 + ((y2 - y1) - total_height) // 2
        for idx, line in enumerate(lines):
            if align == "left":
                x = x1 + 34
            else:
                x = x1 + ((x2 - x1) - line_widths[idx]) // 2
            if style.get("highlight_mode") == "sweep":
                sweep_width = min(line_widths[idx], max(80, int(line_widths[idx] * 0.46)))
                draw.rounded_rectangle(
                    (x - 14, y - 8, x + sweep_width + 18, y + line_heights[idx] + 16),
                    radius=14,
                    fill=self._hex_or_rgba(style.get("accent"), alpha=150),
                )
            if style.get("highlight_mode") == "word":
                self._draw_line_with_highlight(draw, line, x, y, font, style)
            else:
                draw.text(
                    (x, y),
                    line,
                    font=font,
                    fill=style["fill"],
                    stroke_width=style["stroke_width"],
                    stroke_fill=style["stroke"],
                )
            y += line_heights[idx] + line_spacing

    def _hex_or_rgba(self, value, alpha: int = 255):
        if not isinstance(value, str) or not value.startswith("#") or len(value) not in (4, 7):
            return (255, 255, 255, alpha)
        if len(value) == 4:
            value = "#" + "".join(ch * 2 for ch in value[1:])
        try:
            return (
                int(value[1:3], 16),
                int(value[3:5], 16),
                int(value[5:7], 16),
                alpha,
            )
        except ValueError:
            return (255, 255, 255, alpha)

    def _draw_line_with_hormozi_active_word(self, draw: ImageDraw.ImageDraw, image: Image.Image, words_in_line: list, active_word_str: str, x: int, y: int, font: ImageFont.FreeTypeFont, style: dict):
        cursor_x = x
        for idx, word_obj in enumerate(words_in_line):
            word_str = word_obj["word"]
            token = word_str + (" " if idx < len(words_in_line) - 1 else "")

            w_clean = word_str.strip(".,!?;:\"'()[]{}“”")
            a_clean = active_word_str.strip(".,!?;:\"'()[]{}“”")
            is_active = (w_clean.lower() == a_clean.lower())

            if is_active:
                fill = "#00FF66"
                scale = 1.1
            else:
                fill = "#FFDE4D" if self._is_keyword(word_str) else (style.get("fill") or "white")
                scale = 1.0

            if scale == 1.0:
                draw.text(
                    (cursor_x, y),
                    token,
                    font=font,
                    fill=fill,
                    stroke_width=style["stroke_width"],
                    stroke_fill=style["stroke"],
                )
                bbox = draw.textbbox((0, 0), token, font=font)
                cursor_x += bbox[2] - bbox[0]
            else:
                active_fontsize = int(font.size * scale)
                try:
                    active_font = ImageFont.truetype(self.font_path, active_fontsize)
                except Exception:
                    active_font = font

                temp_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
                w_bbox = temp_draw.textbbox((0, 0), token, font=active_font)
                w_w = w_bbox[2] - w_bbox[0] + 40
                w_h = w_bbox[3] - w_bbox[1] + 40

                word_img = Image.new("RGBA", (w_w, w_h), (0, 0, 0, 0))
                word_draw = ImageDraw.Draw(word_img)

                word_draw.text(
                    (20, 20),
                    token,
                    font=active_font,
                    fill=fill,
                    stroke_width=style["stroke_width"],
                    stroke_fill=style["stroke"],
                )

                angle = random.choice([-2, 2, -1, 1])
                rotated_word = word_img.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)

                offset_y = (rotated_word.height - w_h) // 2
                image.paste(rotated_word, (cursor_x - 20, y - 20 - offset_y), rotated_word)
                cursor_x += w_bbox[2] - w_bbox[0]

    def _create_hormozi_subtitle_png(self, chunk: list, active_word_str: str, output_path: str, size=(1080, 1920), visual_style_plan: dict | None = None, glow: bool = False) -> str:
        image = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        visual_style_plan = visual_style_plan or {}
        accent = visual_style_plan.get("accent", "#ff3df2")
        style_name = visual_style_plan.get("caption_style") or visual_style_plan.get("subtitle_style", "bold_punchy")
        subtitle_style = dict(self._subtitle_style(style_name, accent))

        if glow:
            subtitle_style["stroke_width"] = subtitle_style.get("stroke_width", 5) + 4
            subtitle_style["fill"] = accent

        safe_zone = visual_style_plan.get("safe_zone") or {"x": 96, "top": 180, "bottom": 380}
        margin_x = int(safe_zone.get("x", 96))
        max_width = size[0] - (margin_x * 2) - 70

        font, lines = self._fit_font(
            " ".join([item["word"] for item in chunk]),
            max_width=max_width,
            max_lines=3,
            start_size=subtitle_style["font_size"]
        )

        panel_height = 118 + (len(lines) - 1) * 56
        y_center = 1100
        y1 = y_center - panel_height // 2
        y2 = y_center + panel_height // 2

        if subtitle_style.get("box"):
            draw.rounded_rectangle((margin_x, y1, size[0] - margin_x, y2), radius=28, fill=subtitle_style["box"], outline=subtitle_style.get("box_outline"), width=2)
            accent_col = subtitle_style.get("accent")
            if accent_col:
                try:
                    draw.rounded_rectangle((margin_x, y1, margin_x + 14, y2), radius=7, fill=accent_col)
                except Exception:
                    pass

        words_in_lines = []
        current_line = []
        dummy_img = Image.new("RGBA", (1, 1))
        dummy_draw = ImageDraw.Draw(dummy_img)

        for w in chunk:
            w_str = w["word"]
            test_line = " ".join([item["word"] for item in current_line] + [w_str])
            bbox = dummy_draw.textbbox((0, 0), test_line, font=font)
            width = bbox[2] - bbox[0]
            if width <= max_width or not current_line:
                current_line.append(w)
            else:
                words_in_lines.append(current_line)
                current_line = [w]
        if current_line:
            words_in_lines.append(current_line)

        line_heights = []
        for line_w in words_in_lines:
            line_text = " ".join([item["word"] for item in line_w])
            bbox = draw.textbbox((0, 0), line_text, font=font)
            line_heights.append(bbox[3] - bbox[1])

        line_spacing = 14
        total_height = sum(line_heights) + max(0, len(words_in_lines) - 1) * line_spacing
        y_start = y1 + (panel_height - total_height) // 2

        for idx, line_words in enumerate(words_in_lines):
            line_text = " ".join([item["word"] for item in line_words])
            bbox = draw.textbbox((0, 0), line_text, font=font)
            line_width = bbox[2] - bbox[0]
            x = margin_x + (max_width - line_width) // 2

            self._draw_line_with_hormozi_active_word(
                draw, image, line_words, active_word_str, x, y_start, font, subtitle_style
            )
            y_start += line_heights[idx] + line_spacing

        image.save(output_path, "PNG")
        return output_path

    def _create_text_overlay_png(self, text: str, output_path: str, visual_style_plan: dict, overlay_kind: str, size=(1080, 1920), glow: bool = False) -> str:
        image = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        accent = visual_style_plan.get("accent", "#ff3df2")
        style_name = visual_style_plan.get("caption_style") or visual_style_plan.get("subtitle_style", "bold_punchy")
        subtitle_style = dict(self._subtitle_style(style_name, accent))

        if glow:
            subtitle_style["stroke_width"] = subtitle_style.get("stroke_width", 5) + 4
            subtitle_style["fill"] = accent

        safe_zone = visual_style_plan.get("safe_zone") or {"x": 96, "top": 180, "bottom": 380}
        margin_x = int(safe_zone.get("x", 96))

        if overlay_kind == "subtitle":
            max_width = size[0] - (margin_x * 2) - 70
            font, lines = self._fit_font(text, max_width=max_width, max_lines=3, start_size=subtitle_style["font_size"])
            panel_height = 118 + (len(lines) - 1) * 56
            y_center = 1100
            y1 = y_center - panel_height // 2
            y2 = y_center + panel_height // 2
            self._draw_text_panel(draw, lines, font, (margin_x, y1, size[0] - margin_x, y2), subtitle_style)

        elif overlay_kind == "hook":
            hook_style = visual_style_plan.get("hook_style", "center_hook")
            max_width = size[0] - (margin_x * 2) - 70
            font, lines = self._fit_font(text, max_width=max_width, max_lines=3, start_size=72, min_size=42)
            if hook_style == "top_headline":
                box = (margin_x, 150, size[0] - margin_x, 410)
                align = "left"
            elif hook_style == "headline_panel":
                box = (margin_x, 250, size[0] - margin_x, 560)
                align = "center"
            else:
                box = (margin_x, 540, size[0] - margin_x, 850)
                align = "center"
            style = dict(subtitle_style)
            style.update({"font_size": 72, "box": (0, 0, 0, 178), "box_outline": (255, 255, 255, 48)})
            self._draw_text_panel(draw, lines, font, box, style, align=align)

        elif overlay_kind == "cta":
            font, lines = self._fit_font(text, max_width=760, max_lines=2, start_size=46, min_size=32)
            style = dict(subtitle_style)
            style.update({"box": (255, 255, 255, 220), "fill": "#101010", "stroke": "white", "stroke_width": 2})
            self._draw_text_panel(draw, lines, font, (150, 1450, 930, 1605), style)

        image.save(output_path, "PNG")
        return output_path

    def create_subtitle_png(self, text: str, output_path: str, size=(1080, 1920), visual_style_plan: dict | None = None, glow: bool = False) -> str:
        """
        Dùng Pillow vẽ chữ viền đen nền trong suốt.
        """
        if visual_style_plan:
            return self._create_text_overlay_png(text, output_path, visual_style_plan, "subtitle", size=size, glow=glow)

        image = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        fontsize = 55
        try:
            font = ImageFont.truetype(self.font_path, fontsize)
        except Exception:
            font = ImageFont.load_default()

        max_width = 840
        lines = self.wrap_text(text, font, max_width)

        try:
            bbox = draw.textbbox((0, 0), "Ag", font=font)
            line_height = bbox[3] - bbox[1]
        except AttributeError:
            line_height = font.getbbox("Ag")[3]

        line_spacing = 15
        total_height = len(lines) * line_height + (len(lines) - 1) * line_spacing

        y_position_center = 1280
        start_y = y_position_center - total_height // 2

        stroke_width = 8 if glow else 4
        fill_color = "#ff3df2" if glow else "white"

        for i, line in enumerate(lines):
            try:
                bbox = draw.textbbox((0, 0), line, font=font)
                text_width = bbox[2] - bbox[0]
            except AttributeError:
                text_width = font.getbbox(line)[2]

            x_position = (size[0] - text_width) // 2
            y_pos = start_y + i * (line_height + line_spacing)

            words = line.split()
            cursor_x = x_position
            for idx, word in enumerate(words):
                token = word + (" " if idx < len(words) - 1 else "")
                fill = self._get_semantic_color(word, fill_color)

                draw.text(
                    (cursor_x, y_pos),
                    token,
                    font=font,
                    fill=fill,
                    stroke_width=stroke_width,
                    stroke_fill="black"
                )

                try:
                    w_bbox = draw.textbbox((0, 0), token, font=font)
                    w_width = w_bbox[2] - w_bbox[0]
                except AttributeError:
                    w_width = font.getbbox(token)[2]
                cursor_x += w_width

        image.save(output_path, "PNG")
        return output_path
