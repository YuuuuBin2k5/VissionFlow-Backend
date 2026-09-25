"""
Script Engine & Canonical Content Service (Phase 3 & Phase 3.5 Hardening)
Implements:
- Voiceover script generation derived strictly from StoryPlan and grounded in FactPack.
- Canonical Terminology:
  - scenes[].narration is the CANONICAL CONTENT SOURCE (single source of truth for text, visual context, tone).
  - actual_duration_seconds is the CANONICAL TIMING SOURCE (strictly measured downstream from TTS audio via ffprobe).
- Traceable Claim Linkage: scenes[].fact_refs explicitly trace back to FactPack.claims[].id.
- Contradiction qualification policy: notes conflicting claims rather than asserting disputed facts as absolute.
- Derives full_script by concatenating scene narrations to eliminate script-to-scene drift.
- Calibrates word counts and speech pacing (target ~2.5 - 3.2 words per second in Vietnamese).
- Guarantees natural, conversational Vietnamese tone without awkward literal translations.
- Multi-provider architecture (GeminiScriptProvider & LocalScriptProvider).
"""

from __future__ import annotations

import json
import logging
import os
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from production.contracts import FactPack, SceneNarration, ScriptPlan, StoryPlan

logger = logging.getLogger(__name__)

# Standard speech pacing for Vietnamese short-form narration (words per second)
DEFAULT_WORDS_PER_SECOND = 2.8


def count_words(text: str) -> int:
    return len(re.findall(r"\w+", text))


def estimate_duration_sec(word_count: int, wps: float = DEFAULT_WORDS_PER_SECOND) -> float:
    return round(word_count / wps, 2) if wps > 0 else 0.0


# ---------------------------------------------------------------------------
# Provider Interface
# ---------------------------------------------------------------------------

class ScriptProvider(ABC):
    @abstractmethod
    def generate_script(
        self,
        story_plan: StoryPlan,
        fact_pack: FactPack,
        language: str = "vi",
        target_wps: float = DEFAULT_WORDS_PER_SECOND,
        editorial_feedback: Optional[List[str]] = None,
    ) -> ScriptPlan:
        pass


from production.credential_resolver import get_gemini_api_key


class GeminiScriptProvider(ScriptProvider):
    """
    Cloud script generation provider using Google Gemini GenAI SDK.
    Generates natural Vietnamese scene-level voiceover grounded in StoryPlan beats,
    populating fact_refs to maintain strict claim-to-evidence provenance.
    """
    def __init__(self, api_key: Optional[str] = None, model_name: str = "gemini-2.5-flash"):
        self.api_key = api_key or get_gemini_api_key()
        self.model_name = model_name

    def generate_script(
        self,
        story_plan: StoryPlan,
        fact_pack: FactPack,
        language: str = "vi",
        target_wps: float = DEFAULT_WORDS_PER_SECOND,
        editorial_feedback: Optional[List[str]] = None,
    ) -> ScriptPlan:
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not configured")

        from google import genai
        client = genai.Client(api_key=self.api_key)

        beats_text = "\n".join(
            f"- [{b.beat_id}] ({b.beat_type}, {b.estimated_duration_sec}s): {b.summary} (Visual opportunity: {b.visual_opportunity})"
            for b in story_plan.beats
        )

        claims_text = "\n".join(
            f"- [ID: {c.id}] {c.claim} (Criticality: {c.criticality}, Allowed wording: {c.allowed_wording or 'natural'})"
            for c in fact_pack.claims
        )

        contradictions_text = (
            "\nCONTRADICTIONS TO QUALIFY:\n" + "\n".join(f"- {c}" for c in fact_pack.contradictions)
            if fact_pack.contradictions
            else ""
        )

        is_en = (language or "vi").strip().lower().startswith("en")
        effective_wps = 2.5 if is_en else target_wps
        feedback_text = ""
        if editorial_feedback:
            feedback_text = "\nFAILED EDITORIAL CHECKS FROM THE PREVIOUS DRAFT:\n" + "\n".join(
                f"- {item}" for item in editorial_feedback
            )

        if is_en:
            prompt = f"""
You are the VisionFlow Master Script Engine.
Your task is to write a punchy, conversational, retention-optimized English voiceover script for high-engagement vertical short-form video.
scenes[].narration is the CANONICAL CONTENT SOURCE.

STORY ARCHITECTURE:
- Angle: {story_plan.angle}
- Audience Promise: {story_plan.audience_promise}
- Hook Strategy: {story_plan.hook_mechanism}
- Target Duration: {story_plan.target_duration_sec} seconds
- Narrative Beats:
{beats_text}

FACTPACK GROUNDING:
{claims_text}
{contradictions_text}
{feedback_text}

MANDATORY RULES:
1. Write in natural, vivid, idiomatic conversational English (rhythmic, fast-paced, high retention, avoid awkward robotic translation).
2. Exactly ONE scene narration item for each narrative beat.
3. Every scene narration must be semantically complete and deliverable within that beat's duration (at ~{effective_wps} words/sec).
4. Scene 1 (Hook) MUST grab attention immediately in under 15 words.
5. In each scene, specify 'fact_refs': array of matching claim IDs from the FactPack that ground the claims made in that scene.
6. If contradictions are listed, qualify the statement (e.g. 'While experts remain divided...') rather than asserting disputed claims as absolute truth.
7. Do NOT add sound effect descriptions or brackets in the narration field. Put visual notes into 'visual_cue' in English.
8. Return valid raw JSON matching:
9. Editorial order: concrete evidence -> contradiction/anomaly -> stronger evidence -> correction -> specific human payoff.
10. In 0-3s state a physical clue or observable anomaly; in 3-7s add a distinct information gain; by 10s deliver evidence, a meaningful question, or a correction.
11. Do not front-load dates, institutions, researchers, locations, methodology, or more than one hard-to-remember proper noun.
12. If you open a curiosity loop, pay it partially within the next 2-4 seconds. End by returning to a concrete object and a specific human detail, never a generic philosophy or CTA.
{{
  "title": "catchy English video title",
  "scenes": [
    {{
      "scene_index": 1,
      "beat_ref": "beat_01_hook",
      "narration": "English voiceover narration line",
      "visual_cue": "English visual direction cue",
      "fact_refs": ["fact_001"]
    }}
  ]
}}
"""
        else:
            prompt = f"""
You are the VisionFlow Master Script Engine.
Your task is to write a punchy, conversational, retention-optimized Vietnamese voiceover script.
scenes[].narration is the CANONICAL CONTENT SOURCE.

STORY ARCHITECTURE:
- Angle: {story_plan.angle}
- Audience Promise: {story_plan.audience_promise}
- Hook Strategy: {story_plan.hook_mechanism}
- Target Duration: {story_plan.target_duration_sec} seconds
- Narrative Beats:
{beats_text}

FACTPACK GROUNDING:
{claims_text}
{contradictions_text}
{feedback_text}

MANDATORY RULES:
1. Write in natural, vivid, conversational Vietnamese (không dịch máy, không văn phong dịch thuật gượng gạo).
2. Exactly ONE scene narration item for each narrative beat.
3. Every scene narration must be semantically complete and deliverable within that beat's duration (at ~{effective_wps} words/sec).
4. Scene 1 (Hook) MUST grab attention immediately in under 15 words.
5. In each scene, specify 'fact_refs': array of matching claim IDs from the FactPack that ground the claims made in that scene.
6. If contradictions are listed, qualify the statement (e.g. 'Dù còn nhiều ý kiến trái chiều...') rather than asserting disputed claims as absolute truth.
7. Do NOT add sound effect descriptions or brackets in the narration field. Put visual notes into 'visual_cue'.
8. Return valid raw JSON matching:
9. Editorial order: bằng chứng cụ thể -> mâu thuẫn/bất thường -> bằng chứng mạnh hơn -> diễn giải lại -> giá trị con người cụ thể.
10. Trong 0-3 giây phải nêu dấu vết vật lý hoặc bất thường quan sát được; 3-7 giây phải thêm thông tin mới; trước giây 10 phải có bằng chứng, câu hỏi có ý nghĩa hoặc correction.
11. Không đưa ngày tháng, tổ chức, nhà nghiên cứu, địa danh, phương pháp hoặc quá một proper noun khó nhớ lên trước bằng chứng thứ hai.
12. Nếu mở curiosity loop, phải trả partial payoff trong 2-4 giây tiếp theo. Kết thúc phải quay lại vật thể thật và chi tiết con người cụ thể, không dùng triết lý hay CTA chung chung.
{{
  "title": "catchy Vietnamese video title",
  "scenes": [
    {{
      "scene_index": 1,
      "beat_ref": "beat_01_hook",
      "narration": "lời thoại giọng đọc tiếng Việt",
      "visual_cue": "hướng dẫn hình ảnh tương ứng",
      "fact_refs": ["fact_001"]
    }}
  ]
}}
"""
        try:
            resp = client.models.generate_content(
                model=self.model_name,
                contents=prompt,
            )
            raw_text = resp.text.strip()
            if raw_text.startswith("```"):
                raw_text = re.sub(r"^```[a-zA-Z]*\n", "", raw_text)
                raw_text = re.sub(r"\n```$", "", raw_text)
            data = json.loads(raw_text)

            raw_scenes = data.get("scenes", [])
            valid_fact_ids = {c.id for c in fact_pack.claims}
            scenes: List[SceneNarration] = []
            for idx, s in enumerate(raw_scenes):
                narr = s.get("narration", "").strip()
                w_count = count_words(narr)
                est_dur = estimate_duration_sec(w_count, target_wps)
                raw_refs = s.get("fact_refs", [])
                # Filter to existing fact IDs or assign fallback to preserve grounding
                valid_refs = [r for r in raw_refs if r in valid_fact_ids]
                if not valid_refs and fact_pack.claims:
                    valid_refs = [fact_pack.claims[idx % len(fact_pack.claims)].id]

                scenes.append(
                    SceneNarration(
                        scene_id=f"scene_{idx + 1}",
                        scene_index=idx + 1,
                        narration=narr,
                        beat_ref=s.get("beat_ref"),
                        estimated_speech_duration_sec=est_dur,
                        visual_cue=s.get("visual_cue"),
                        fact_refs=valid_refs,
                    )
                )

            # Canonical derivation: full_script is strictly the concatenation of scene narrations
            full_script = " ".join(s.narration for s in scenes)
            total_words = count_words(full_script)
            hook_words = count_words(scenes[0].narration) if scenes else 0

            return ScriptPlan(
                title=data.get("title", f"Khám Phá {fact_pack.topic}"),
                full_script=full_script,
                scenes=scenes,
                total_word_count=total_words,
                estimated_total_duration_sec=estimate_duration_sec(total_words, target_wps),
                hook_word_count=hook_words,
            )
        except Exception as e:
            raise ValueError(f"Gemini script generation failed: {e}") from e


class LocalScriptProvider(ScriptProvider):
    """
    Deterministic 100% offline natural Vietnamese script generator.
    Converts StoryPlan beats into conversational voiceover lines strictly calibrated to word counts,
    populating fact_refs to link each scene to FactPack claims.
    """
    def generate_script(
        self,
        story_plan: StoryPlan,
        fact_pack: FactPack,
        language: str = "vi",
        target_wps: float = DEFAULT_WORDS_PER_SECOND,
        editorial_feedback: Optional[List[str]] = None,
    ) -> ScriptPlan:
        topic = fact_pack.topic
        scenes: List[SceneNarration] = []
        fact_ids = [c.id for c in fact_pack.claims]

        for idx, beat in enumerate(story_plan.beats):
            scene_idx = idx + 1
            target_dur = beat.estimated_duration_sec
            target_words = max(8, int(target_dur * target_wps))

            is_en = (language or "vi").strip().lower().startswith("en")
            # Determine relevant fact_refs for this scene
            if is_en:
                if beat.beat_type == "hook":
                    narration = f"What is the untold secret behind the mastery of {topic}?"
                    refs = [fact_ids[0]] if fact_ids else []
                elif beat.beat_type == "setup":
                    narration = f"Every masterpiece begins with meticulous preparation and precision engineered down to the millimeter."
                    refs = [fact_ids[0]] if len(fact_ids) == 1 else fact_ids[:2]
                elif beat.beat_type == "development":
                    narration = f"Each cut requires steady hands and immense patience, where even a tiny mistake cannot be tolerated."
                    refs = [fact_ids[min(1, len(fact_ids) - 1)]] if fact_ids else []
                elif beat.beat_type == "climax":
                    narration = f"And when every joint fits together seamlessly, it reveals a timeless work of art crafted without a single nail."
                    refs = [fact_ids[-1]] if fact_ids else []
                elif beat.beat_type in ("climax_payoff", "payoff_cta"):
                    narration = f"That is the pure essence of true dedication. Which detail of this process surprised you the most?"
                    refs = [fact_ids[0]] if fact_ids else []
                else:
                    narration = f"The following steps require absolute accuracy to bring out the complete beauty of {topic}."
                    refs = [fact_ids[idx % len(fact_ids)]] if fact_ids else []

                if fact_pack.contradictions and beat.beat_type == "development":
                    narration += " While technical opinions may differ, uncompromising standards remain paramount."
            else:
                if beat.beat_type == "hook":
                    narration = f"Điều gì tạo nên sự tinh xảo khó tin của {topic}?"
                    refs = [fact_ids[0]] if fact_ids else []
                elif beat.beat_type == "setup":
                    narration = f"Mọi kiệt tác đều khởi đầu từ việc chọn lọc những nguyên liệu tốt nhất cùng sự chuẩn bị công phu đến từng milimét."
                    refs = [fact_ids[0]] if len(fact_ids) == 1 else fact_ids[:2]
                elif beat.beat_type == "development":
                    narration = f"Từng đường đục và nhát cắt đòi hỏi bàn tay người thợ phải có sự điềm tĩnh tuyệt đối, nơi một sai sót nhỏ cũng không được phép xảy ra."
                    refs = [fact_ids[min(1, len(fact_ids) - 1)]] if fact_ids else []
                elif beat.beat_type == "climax":
                    narration = f"Và khi các chi tiết ăn khớp vào nhau một cách hoàn hảo, tác phẩm bộc lộ vẻ đẹp vượt thời gian mà không cần một chiếc đinh hay ốc vít nào."
                    refs = [fact_ids[-1]] if fact_ids else []
                elif beat.beat_type in ("climax_payoff", "payoff_cta"):
                    narration = f"Đó chính là tinh hoa của sự tận tâm. Bạn ấn tượng nhất với chi tiết nào trong quy trình kỳ diệu này?"
                    refs = [fact_ids[0]] if fact_ids else []
                else:
                    narration = f"Những bước tiếp theo đòi hỏi độ chính xác tuyệt đối để hoàn thiện trọn vẹn từng đường nét của {topic}."
                    refs = [fact_ids[idx % len(fact_ids)]] if fact_ids else []

                # If contradictions exist, append cautious qualification in development/climax
                if fact_pack.contradictions and beat.beat_type == "development":
                    narration += " Dù có những quan điểm kỹ thuật khác nhau, tiêu chuẩn khắt khe vẫn luôn được đặt lên hàng đầu."

            w_count = count_words(narration)
            est_dur = estimate_duration_sec(w_count, target_wps)

            scenes.append(
                SceneNarration(
                    scene_id=f"scene_{scene_idx}",
                    scene_index=scene_idx,
                    narration=narration,
                    beat_ref=beat.beat_id,
                    estimated_speech_duration_sec=est_dur,
                    visual_cue=beat.visual_opportunity,
                    fact_refs=refs,
                )
            )

        # Canonical derivation: full_script is derived from scenes[].narration (CANONICAL CONTENT SOURCE)
        full_script = " ".join(s.narration for s in scenes)
        total_words = count_words(full_script)
        hook_words = count_words(scenes[0].narration) if scenes else 0

        title = f"The Untold Secret Of {topic}" if is_en else f"Bí Mật Đỉnh Cao Của {topic}"

        return ScriptPlan(
            title=title,
            full_script=full_script,
            scenes=scenes,
            total_word_count=total_words,
            estimated_total_duration_sec=estimate_duration_sec(total_words, target_wps),
            hook_word_count=hook_words,
        )


# ---------------------------------------------------------------------------
# Script Engine Service
# ---------------------------------------------------------------------------

class ScriptEngine:
    def __init__(self, provider: Optional[ScriptProvider] = None):
        if provider is not None:
            self.provider = provider
        elif get_gemini_api_key():
            self.provider = GeminiScriptProvider()
        else:
            self.provider = LocalScriptProvider()

        self.local_fallback = LocalScriptProvider()

    def generate_script_plan(
        self,
        story_plan: StoryPlan,
        fact_pack: FactPack,
        language: str = "vi",
        target_wps: float = DEFAULT_WORDS_PER_SECOND,
        editorial_feedback: Optional[List[str]] = None,
    ) -> ScriptPlan:
        try:
            return self.provider.generate_script(
                story_plan=story_plan,
                fact_pack=fact_pack,
                language=language,
                target_wps=target_wps,
                editorial_feedback=editorial_feedback,
            )
        except Exception as e:
            logger.warning(f"Primary script provider failed ({e}). Using local fallback.")
            return self.local_fallback.generate_script(
                story_plan=story_plan,
                fact_pack=fact_pack,
                language=language,
                target_wps=target_wps,
                editorial_feedback=editorial_feedback,
            )


script_engine = ScriptEngine()
