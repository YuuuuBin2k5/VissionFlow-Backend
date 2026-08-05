# Rule: Video Metadata & Title/Description Generation Standards

## Overview
This rule enforces strict architectural and copywriting standards for generating video titles, SEO descriptions, pinned comments, and hashtags across all VisionFlow pipelines (**Video Short** and **AI Dubbing**).

---

## 1. Architectural & Design Pattern Constraints
1. **Zero Code Duplication**: ALL title, description, and metadata generation logic MUST be executed through the unified `UnifiedVideoMetadataService` facade (`worker/services/unified_metadata_service.py`).
2. **Strategy Pattern Requirement**: Language-specific prompting and formatting MUST be encapsulated inside concrete strategy implementations (`VietnameseMetadataStrategy`, `EnglishMetadataStrategy`) adhering to the `MetadataGenerationStrategy` interface.
3. **Factory Pattern Requirement**: The creation of strategies MUST be resolved via `MetadataStrategyFactory` based on `target_language` ("vi", "en", "auto").
4. **No Untranslated Text**: When processing Douyin / TikTok China links, raw Chinese titles (`original_video_title`) MUST NEVER be exposed to end users in Video Vault, Review Queue, or Control Tower without translation into the chosen target language.

---

## 2. Copywriting & SEO Rules for Target Languages

### A. Vietnamese Target Language (`target_language = "vi"`)
- **Title (video_title)**: High-converting, viral Vietnamese title (max 70 characters). Must capture the core curiosity hook of the video without clickbait deception.
- **Caption SEO (caption_seo)**: 3-part structured caption:
  1. **Visual Hook**: Curiosity gap opening statement.
  2. **Engagement Question**: Thought-provoking question driving comments.
  3. **Niche SEO Keywords**: Natural paragraph containing core search terms.
- **Pinned Comment (pinned_comment)**: Open-ended, controversial or deep perspective question to stimulate comment section activity.
- **Hashtags (hashtags)**: 4 to 5 hashtags starting with `#`:
  - 1-2 broad niche tags (e.g., `#trietlycuocsong`, #xuhuong`)
  - 2 specific content tags (e.g., `#tuduymo`, `#baihoccuocsong`)
  - 1 mandatory brand tag: `#YuuBin`

### B. English Target Language (`target_language = "en"`)
- **Title (video_title)**: Catchy, high-impact English title (max 70 characters).
- **Caption SEO (caption_seo)**: Engaging English caption tailored for global TikTok/YouTube Shorts viewers with clear call-to-action for comments.
- **Pinned Comment (pinned_comment)**: Engaging question encouraging global viewers to comment.
- **Hashtags (hashtags)**: 4 to 5 English hashtags ending with mandatory brand tag `#YuuBin`.

---

## 3. Immediate Title Sanitization Rule
When a job is created from a foreign link (`source_url` from `douyin.com` or `tiktok.com`):
- `dubbing.py` / `UnifiedVideoMetadataService.sanitize_title()` MUST translate or format the project title immediately into `[VI] ...` or `[EN] ...` so untranslated foreign titles are never shown.
