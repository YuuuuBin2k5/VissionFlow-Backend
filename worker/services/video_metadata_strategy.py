"""
Strategy Pattern for Multi-Language Video Title & SEO Metadata Generation
========================================================================
Design Pattern: Strategy Pattern + Factory Pattern

Provides language-specific title, description (caption SEO), pinned comment,
and hashtag generation for both Video Short and AI Dubbing pipelines.
"""

from __future__ import annotations

import abc
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any


def remove_vietnamese_accents(text: str) -> str:
    if not text:
        return ""
    text = text.replace("đ", "d").replace("Đ", "D")
    normalized = unicodedata.normalize("NFD", text)
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn")


def sanitize_hashtag(tag: str) -> str:
    if not tag:
        return ""
    tag = str(tag).strip()
    body = tag if not tag.startswith("#") else tag[1:]
    unaccented = remove_vietnamese_accents(body)
    clean = re.sub(r"[^\w]", "", unaccented)
    if not clean:
        return ""
    if clean.lower() == "yuubin":
        return "#YuuBin"
    return f"#{clean.lower()}"


@dataclass(frozen=True)
class VideoMetadataResult:
    title: str
    caption_seo: str
    pinned_comment: str
    hashtags: list[str] = field(default_factory=list)
    video_script: str = ""
    cta_keyword: str = ""
    loop_hook: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "caption_seo": self.caption_seo,
            "pinned_comment": self.pinned_comment,
            "hashtags": self.hashtags,
            "video_script": self.video_script,
            "cta_keyword": self.cta_keyword,
            "loop_hook": self.loop_hook,
        }


class MetadataGenerationStrategy(abc.ABC):
    """Abstract Strategy interface for multi-language metadata generation."""

    @abc.abstractmethod
    def generate(self, transcript: str, original_title: str | None = None, storytelling_framework: str | None = None) -> VideoMetadataResult:
        """Generate structured title, caption SEO, pinned comment, and hashtags."""
        pass

    @abc.abstractmethod
    def translate_raw_title(self, raw_title: str) -> str:
        """Quickly translate/sanitize a foreign title into the target language."""
        pass


class VietnameseMetadataStrategy(MetadataGenerationStrategy):
    """Concrete Strategy for Vietnamese Title & SEO Metadata."""

    def generate(self, transcript: str, original_title: str | None = None, storytelling_framework: str | None = "mid_action_open") -> VideoMetadataResult:
        title_context = f"\nTIEU DE GOC CUA VIDEO NUOC NGOAI: \"{original_title}\"" if original_title else ""
        framework_context = f"\nCAU TRUC KE CHUYEN YEU CAU: \"{storytelling_framework or 'mid_action_open'}\" (mid_action_open: Mở đầu cao trào -> tua ngược giải thích -> bài học; myth_vs_reality: Lầm tưởng -> Sự thật -> Giải pháp; transformation_twist: Khó khăn -> Thử thách -> Bất ngờ -> Bài học)"

        prompt = f"""
Hay đóng vai là một chuyên gia marketing và SEO video TikTok/YouTube Shorts hàng đầu Việt Nam.
Hãy phân tích nội dung lời thoại tiếng Việt đã dịch/lồng tiếng dưới đây để tối ưu hóa SEO và tạo ra kết quả dưới định dạng JSON block hợp lệ.
{title_context}
{framework_context}

LOI THOAI / SCRIPT:
---
{transcript}
---

NHIEM VU THỰC THI:
1. Đọc kỹ kịch bản thuyết minh tiếng Việt và tiến hành viết lại, nâng cấp toàn diện kịch bản dưới trường "video_script".
   - QUY TẮC "KHOẢNG TRẮNG TÒ MÒ" (CURIOSITY GAP): Cứ mỗi 7-10 giây, AI bắt buộc phải nhúng một "Khoảng trắng tò mò" bằng các cụm từ bẻ gãy tư duy tuyến tính để kích thích giữ chân người xem.
   - QUY TẮC "KỊCH BẢN VÒNG LẶP VÔ TẬN" (SEAMLESS LOOP): Câu thoại cuối cùng của video_script BẮT BUỘC phải tạo vế mở hoặc câu dẫn nối liền mạch về nghĩa và ngữ điệu quay trở lại ngay câu Hook mở đầu (00:00 - 00:03).
   - TỪ KHÓA CTA KÊU GỌI BÌNH LUẬN: Tự động tạo 1 từ khóa tương tác VIẾT HOA ngắn gọn (ví dụ: "BÀI HỌC", "BÍ MẬT", "TỰ ĐỘNG"). 3 giây cuối lời thoại video_script BẮT BUỘC có câu: "Bình luận [TỪ_KHÓA] bên dưới để xem thêm!"
2. Sinh tiêu đề ngắn gọn (dưới 70 ký tự tiếng Việt), cực kỳ thu hút, không giật gân sai sự thật.
3. Sinh đoạn văn mô tả SEO (caption_seo) gồm 3 phần: (1) Hook thị giác, (2) Câu kêu gọi bình luận từ khóa CTA [TỪ_KHÓA], (3) Các từ khóa SEO ngách.
4. Sinh câu hỏi ghim (pinned_comment) kêu gọi bình luận từ khóa CTA [TỪ_KHÓA] gây tranh luận tích cực.
5. Danh sách hashtags từ 4-5 thẻ, bắt đầu bằng dấu #, bắt buộc có thẻ thương hiệu #YuuBin.

BẮT BUỘC trả về định dạng JSON duy nhất với cấu trúc:
{{
  "title": "Tiêu đề tiếng Việt cực kỳ cuốn hút",
  "video_script": "Kịch bản thuyết minh tiếng Việt đã được nâng cấp seamless loop...",
  "caption_seo": "Đoạn văn mô tả thu hút có kêu gọi bình luận [TỪ_KHÓA]...",
  "pinned_comment": "Bình luận ghim kêu gọi gõ [TỪ_KHÓA]...",
  "cta_keyword": "BÀI HỌC",
  "loop_hook": "Câu dẫn nối về đầu video",
  "hashtags": ["#trietlycuocsong", "#tuduymo", "#xuhuong", "#YuuBin"]
}}
CHỈ TRẢ VỀ JSON HỢP LỆ. KHÔNG CHỨA BẤT KỲ VĂN BẢN NÀO KHÁC.
"""
        from worker.services.llm_service import LLMService
        llm = LLMService()
        raw_response = llm._call_gemini_with_fallback(prompt, lambda: "{}")
        return self._parse_json_result(raw_response, transcript, original_title)

    def translate_raw_title(self, raw_title: str) -> str:
        if not raw_title or not raw_title.strip():
            return "Video Lồng Tiếng Việt"
        if not any("\u4e00" <= char <= "\u9fff" for char in raw_title):
            return raw_title.strip()[:100]

        from worker.services.llm_service import LLMService

        prompt = f"""Dịch tiêu đề tiếng Trung / nước ngoài sau sang tiêu đề tiếng Việt cuốn hút, súc tích (dưới 70 ký tự) cho video TikTok:
"{raw_title}"
Chỉ trả về 1 câu tiêu đề tiếng Việt duy nhất, không kèm giải thích hay dấu ngoặc kép."""
        try:
            llm = LLMService()
            translated = llm._call_gemini_with_fallback(prompt, lambda: f"Video Lồng Tiếng: {raw_title[:40]}")
            clean = translated.strip().strip('"').strip("'")
            return clean if clean else f"Video Lồng Tiếng: {raw_title[:40]}"
        except Exception:
            return f"Video Lồng Tiếng: {raw_title[:40]}"

    def _parse_json_result(self, raw_response: str, fallback_script: str, original_title: str | None) -> VideoMetadataResult:
        try:
            clean = raw_response.strip()
            if "```json" in clean:
                clean = clean.split("```json")[1].split("```")[0].strip()
            elif "```" in clean:
                clean = clean.split("```")[1].split("```")[0].strip()
            data = json.loads(clean)
            raw_tags = data.get("hashtags") or ["#xuhuong", "#gocchiemnghiem", "#YuuBin"]
            sanitized_tags = [sanitize_hashtag(t) for t in raw_tags if sanitize_hashtag(t)]
            if "#YuuBin" not in sanitized_tags and "#yuubin" not in [t.lower() for t in sanitized_tags]:
                sanitized_tags.append("#YuuBin")
            return VideoMetadataResult(
                title=str(data.get("title") or original_title or "Video lồng tiếng mới").strip()[:100],
                caption_seo=str(data.get("caption_seo") or fallback_script[:200]).strip(),
                pinned_comment=str(data.get("pinned_comment") or "Bạn nghĩ sao về video này? Bình luận phía dưới nhé!").strip(),
                hashtags=sanitized_tags[:5],
                video_script=str(data.get("video_script") or fallback_script).strip(),
                cta_keyword=str(data.get("cta_keyword") or "BÀI HỌC").upper().strip(),
                loop_hook=str(data.get("loop_hook") or "").strip(),
            )
        except Exception:
            return VideoMetadataResult(
                title=(original_title or "Video lồng tiếng mới")[:100],
                caption_seo=fallback_script[:250],
                pinned_comment="Đọc bình luận ghim để xem góc nhìn chuyên sâu...",
                hashtags=["#gocchiemnghiem", "#dichlongtieng", "#YuuBin"],
                video_script=fallback_script,
            )


class EnglishMetadataStrategy(MetadataGenerationStrategy):
    """Concrete Strategy for English Title & SEO Metadata."""

    def generate(self, transcript: str, original_title: str | None = None, storytelling_framework: str | None = "mid_action_open") -> VideoMetadataResult:
        title_context = f"\nORIGINAL FOREIGN TITLE: \"{original_title}\"" if original_title else ""
        framework_context = f"\nREQUIRED STORYTELLING FRAMEWORK: \"{storytelling_framework or 'mid_action_open'}\" (mid_action_open: Climax hook -> flashback context -> key lesson; myth_vs_reality: Bust myth -> reveal truth -> actionable advice; transformation_twist: Struggle -> challenge -> unexpected twist -> lesson)"

        prompt = f"""
Act as a top-tier viral TikTok & YouTube Shorts marketing expert for English-speaking global audiences.
Analyze the following English dubbed video script/transcript and generate high-converting SEO metadata.
{title_context}
{framework_context}

ENGLISH TRANSCRIPT:
---
{transcript}
---

TASKS & RULES:
1. Rewrite and polish the English narration script under "video_script".
   - CURIOSITY GAP RULE: Insert a curiosity gap hook every 7-10s to break linear thinking and maximize retention.
   - SEAMLESS LOOP RULE: The final sentence of video_script MUST naturally link grammatically and tonally back into the 0-3s opening Hook sentence so viewers loop seamlessly.
   - CTA KEYWORD RULE: Generate 1 short UPPERCASE CTA keyword (e.g. "LESSON", "SECRET", "MINDSET"). In the last 3s of video_script narration, MUST include: "Comment '[CTA_KEYWORD]' below for more!"
2. Generate a catchy, viral English title (under 70 characters).
3. Generate a 3-part English caption_seo: (1) Visual hook, (2) Engagement call-to-action asking viewers to comment [CTA_KEYWORD], (3) Niche SEO keywords.
4. Generate a compelling pinned_comment driving comment engagement for [CTA_KEYWORD].
5. Provide 4-5 English hashtags, including mandatory brand tag #YuuBin.

Return ONLY a valid JSON object with exact schema:
{{
  "title": "Catchy English Video Title",
  "video_script": "Polished English script with seamless loop and CTA keyword...",
  "caption_seo": "Engaging 3-part English description asking for [CTA_KEYWORD]...",
  "pinned_comment": "Thought-provoking question asking for [CTA_KEYWORD]...",
  "cta_keyword": "LESSON",
  "loop_hook": "Leading sentence linking back to 0-3s hook",
  "hashtags": ["#mindset", "#motivation", "#viral", "#YuuBin"]
}}
RETURN ONLY VALID JSON.
"""
        from worker.services.llm_service import LLMService
        llm = LLMService()
        raw_response = llm._call_gemini_with_fallback(prompt, lambda: "{}")
        return self._parse_json_result(raw_response, transcript, original_title)

    def translate_raw_title(self, raw_title: str) -> str:
        if not raw_title or not raw_title.strip():
            return "English Dubbed Video"
        if not any("\u4e00" <= char <= "\u9fff" for char in raw_title):
            return raw_title.strip()[:100]

        from worker.services.llm_service import LLMService

        prompt = f"""Translate this Chinese/foreign video title into a compelling, concise English title (under 70 chars) for TikTok:
"{raw_title}"
Return ONLY the translated English title text."""
        try:
            llm = LLMService()
            translated = llm._call_gemini_with_fallback(prompt, lambda: f"Dubbed Video: {raw_title[:40]}")
            clean = translated.strip().strip('"').strip("'")
            return clean if clean else f"Dubbed Video: {raw_title[:40]}"
        except Exception:
            return f"Dubbed Video: {raw_title[:40]}"

    def _parse_json_result(self, raw_response: str, fallback_script: str, original_title: str | None) -> VideoMetadataResult:
        try:
            clean = raw_response.strip()
            if "```json" in clean:
                clean = clean.split("```json")[1].split("```")[0].strip()
            elif "```" in clean:
                clean = clean.split("```")[1].split("```")[0].strip()
            data = json.loads(clean)
            raw_tags = data.get("hashtags") or ["#shorts", "#dubbed", "#YuuBin"]
            sanitized_tags = [sanitize_hashtag(t) for t in raw_tags if sanitize_hashtag(t)]
            if "#YuuBin" not in sanitized_tags and "#yuubin" not in [t.lower() for t in sanitized_tags]:
                sanitized_tags.append("#YuuBin")
            return VideoMetadataResult(
                title=str(data.get("title") or original_title or "New Dubbed Video").strip()[:100],
                caption_seo=str(data.get("caption_seo") or fallback_script[:200]).strip(),
                pinned_comment=str(data.get("pinned_comment") or "What are your thoughts on this? Let us know below!").strip(),
                hashtags=sanitized_tags[:5],
                video_script=str(data.get("video_script") or fallback_script).strip(),
                cta_keyword=str(data.get("cta_keyword") or "LESSON").upper().strip(),
                loop_hook=str(data.get("loop_hook") or "").strip(),
            )
        except Exception:
            return VideoMetadataResult(
                title=(original_title or "New Dubbed Video")[:100],
                caption_seo=fallback_script[:250],
                pinned_comment="Check out the pinned comment for key takeaways...",
                hashtags=["#mindset", "#dubbed", "#YuuBin"],
                video_script=fallback_script,
            )


class MetadataStrategyFactory:
    """Factory Pattern for resolving the target MetadataGenerationStrategy."""

    @staticmethod
    def get_strategy(target_language: str = "vi", voice_code: str = "") -> MetadataGenerationStrategy:
        lang = str(target_language or "auto").lower().strip()
        voice = str(voice_code or "").lower().strip()

        # If language is 'en' or voice code indicates English voice
        if lang == "en" or voice.startswith("en-") or "adam" in voice or "christopher" in voice:
            return EnglishMetadataStrategy()
        
        # Default to Vietnamese strategy
        return VietnameseMetadataStrategy()
