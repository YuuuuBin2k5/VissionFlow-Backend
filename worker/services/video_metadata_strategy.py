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

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "caption_seo": self.caption_seo,
            "pinned_comment": self.pinned_comment,
            "hashtags": self.hashtags,
            "video_script": self.video_script,
        }


class MetadataGenerationStrategy(abc.ABC):
    """Abstract Strategy interface for multi-language metadata generation."""

    @abc.abstractmethod
    def generate(self, transcript: str, original_title: str | None = None) -> VideoMetadataResult:
        """Generate structured title, caption SEO, pinned comment, and hashtags."""
        pass

    @abc.abstractmethod
    def translate_raw_title(self, raw_title: str) -> str:
        """Quickly translate/sanitize a foreign title into the target language."""
        pass


class VietnameseMetadataStrategy(MetadataGenerationStrategy):
    """Concrete Strategy for Vietnamese Title & SEO Metadata."""

    def generate(self, transcript: str, original_title: str | None = None) -> VideoMetadataResult:
        title_context = f"\nTIEU DE GOC CUA VIDEO NUOC NGOAI: \"{original_title}\"" if original_title else ""
        prompt = f"""
Hay đóng vai là một chuyên gia marketing và SEO video TikTok/YouTube Shorts hàng đầu Việt Nam.
Hãy phân tích nội dung lời thoại tiếng Việt đã dịch/lồng tiếng dưới đây để tối ưu hóa SEO và tạo ra kết quả dưới định dạng JSON block hợp lệ.
{title_context}

LOI THOAI / SCRIPT:
---
{transcript}
---

NHIEM VU:
1. Đọc kỹ kịch bản thuyết minh tiếng Việt và tiến hành viết lại, nâng cấp toàn diện kịch bản dưới trường "video_script".
   - QUY TẮC "KHOẢNG TRẮNG TÒ MÒ" (CURIOSITY GAP): Cứ mỗi 7-10 giây, AI bắt buộc phải nhúng một "Khoảng trắng tò mò" bằng các cụm từ bẻ gãy tư duy tuyến tính để kích thích giữ chân người xem.
2. Sinh tiêu đề ngắn gọn (dưới 70 ký tự tiếng Việt), cực kỳ thu hút, không giật gân sai sự thật.
3. Sinh đoạn văn mô tả SEO (caption_seo) gồm 3 phần: (1) Hook thị giác, (2) Câu hỏi kích thích bình luận, (3) Các từ khóa SEO ngách.
4. Sinh câu hỏi ghim (pinned_comment) gây tranh luận tranh cãi tích cực liên quan đến video.
5. Danh sách hashtags từ 4-5 thẻ, bắt đầu bằng dấu #, bắt buộc có thẻ thương hiệu #YuuBin.

BẮT BUỘC trả về định dạng JSON duy nhất:
{{
  "title": "Tiêu đề tiếng Việt cực kỳ cuốn hút",
  "video_script": "Kịch bản thuyết minh tiếng Việt đã được nâng cấp...",
  "caption_seo": "Đoạn văn mô tả thu hút 3 phần...",
  "pinned_comment": "Câu hỏi ghim gây tò mò dưới bình luận...",
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
        # If title is already clean Vietnamese/English without Chinese/Special characters, return sanitized version
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

    def generate(self, transcript: str, original_title: str | None = None) -> VideoMetadataResult:
        title_context = f"\nORIGINAL FOREIGN TITLE: \"{original_title}\"" if original_title else ""
        prompt = f"""
Act as a top-tier viral TikTok & YouTube Shorts marketing expert for English-speaking global audiences.
Analyze the following English dubbed video script/transcript and generate high-converting SEO metadata.
{title_context}

ENGLISH TRANSCRIPT:
---
{transcript}
---

TASKS:
1. Rewrite and polish the English narration script under "video_script" with curiosity gap hooks every 7-10s.
2. Generate a catchy, viral English title (under 70 characters).
3. Generate a 3-part English caption_seo: (1) Visual hook, (2) Engagement question driving comments, (3) Niche SEO keywords.
4. Generate a compelling pinned_comment question.
5. Provide 4-5 English hashtags, including mandatory brand tag #YuuBin.

Return ONLY a valid JSON object with exact schema:
{{
  "title": "Catchy English Video Title",
  "video_script": "Polished English script with curiosity gaps...",
  "caption_seo": "Engaging 3-part English description...",
  "pinned_comment": "Thought-provoking question pinned in comments...",
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
