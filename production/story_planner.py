"""
Story Planner Engine (Phase 3 & Phase 3.5 Hardening)
Implements:
- Narrative architecture planning without full script generation.
- Dynamic Story Archetypes (8 archetypes):
  - PROCESS_EXPLAINER, MYSTERY, TRANSFORMATION, TIMELINE,
  - CAUSE_EFFECT, COMPARISON, INVESTIGATION, DISCOVERY.
- Automatic archetype inference from instruction/topic context with override support.
- Archetype-specific beat ratios and duration allocation.
- Visual opportunity mapping to inform downstream visual planning.
- Excluded interpretations to prevent cliches and hallucinated tropes.
- Multi-provider support (GeminiStoryPlannerProvider & LocalStoryPlannerProvider).
"""

from __future__ import annotations

import json
import logging
import os
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from production.contracts import FactPack, NarrativeBeat, StoryArchetype, StoryPlan

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Archetype Configurations & Beat Ratios
# ---------------------------------------------------------------------------

ARCHETYPE_BEAT_RATIOS: Dict[StoryArchetype, Dict[str, float]] = {
    StoryArchetype.PROCESS_EXPLAINER: {
        "hook": 0.10,
        "setup": 0.15,
        "development": 0.45,
        "climax": 0.20,
        "payoff_cta": 0.10,
    },
    StoryArchetype.MYSTERY: {
        "hook": 0.20,
        "setup": 0.15,
        "development": 0.25,
        "climax": 0.30,
        "payoff_cta": 0.10,
    },
    StoryArchetype.TRANSFORMATION: {
        "hook": 0.12,
        "setup": 0.18,
        "development": 0.30,
        "climax": 0.30,
        "payoff_cta": 0.10,
    },
    StoryArchetype.TIMELINE: {
        "hook": 0.10,
        "setup": 0.20,
        "development": 0.40,
        "climax": 0.20,
        "payoff_cta": 0.10,
    },
    StoryArchetype.CAUSE_EFFECT: {
        "hook": 0.15,
        "setup": 0.20,
        "development": 0.35,
        "climax": 0.20,
        "payoff_cta": 0.10,
    },
    StoryArchetype.COMPARISON: {
        "hook": 0.12,
        "setup": 0.18,
        "development": 0.40,
        "climax": 0.20,
        "payoff_cta": 0.10,
    },
    StoryArchetype.INVESTIGATION: {
        "hook": 0.18,
        "setup": 0.22,
        "development": 0.30,
        "climax": 0.20,
        "payoff_cta": 0.10,
    },
    StoryArchetype.DISCOVERY: {
        "hook": 0.15,
        "setup": 0.15,
        "development": 0.35,
        "climax": 0.25,
        "payoff_cta": 0.10,
    },
}


def infer_archetype(topic: str, context: Optional[str] = None, override: Optional[str] = None) -> StoryArchetype:
    """
    Infers the optimal narrative archetype based on topic and context, or accepts explicit override.
    """
    if override:
        cleaned_override = override.upper().strip()
        try:
            return StoryArchetype(cleaned_override)
        except ValueError:
            pass

    combined = f"{topic} {context or ''}".lower()

    if any(k in combined for k in ["bí ẩn", "bí mật", "tại sao", "kỳ lạ", "mystery", "secret", "paradox", "uẩn khúc"]):
        return StoryArchetype.MYSTERY
    if any(k in combined for k in ["lịch sử", "dòng thời gian", "tiến trình", "giai đoạn", "năm 19", "năm 20", "timeline", "history", "tiến hóa"]):
        return StoryArchetype.TIMELINE
    if any(k in combined for k in ["nguyên nhân", "hậu quả", "tác động", "dẫn đến", "vì sao", "cause", "effect", "impact", "hệ lụy"]):
        return StoryArchetype.CAUSE_EFFECT
    if any(k in combined for k in ["biến đổi", "lột xác", "trước và sau", "phục hồi", "transformation", "before after", "tái sinh"]):
        return StoryArchetype.TRANSFORMATION
    if any(k in combined for k in ["so sánh", "khác biệt", "đối đầu", "versus", "vs", "comparison", "so với", "hơn kém"]):
        return StoryArchetype.COMPARISON
    if any(k in combined for k in ["điều tra", "sự thật", "bóc trần", "vụ án", "lật tẩy", "investigation", "chân tướng", "manh mối"]):
        return StoryArchetype.INVESTIGATION
    if any(k in combined for k in ["khám phá", "phát hiện", "tìm ra", "vùng đất mới", "discovery", "thám hiểm", "vén màn"]):
        return StoryArchetype.DISCOVERY

    return StoryArchetype.PROCESS_EXPLAINER


# ---------------------------------------------------------------------------
# Provider Interface
# ---------------------------------------------------------------------------

class StoryPlannerProvider(ABC):
    @abstractmethod
    def plan_story(
        self,
        fact_pack: FactPack,
        target_duration_sec: float = 55.0,
        tone: str = "curiosity",
        format_type: str = "short",
        archetype: Optional[StoryArchetype] = None,
    ) -> StoryPlan:
        pass


class GeminiStoryPlannerProvider(StoryPlannerProvider):
    """
    Cloud story planning provider using Google Gemini GenAI SDK.
    Emits strictly validated StoryPlan schemas without writing full script lines.
    """
    def __init__(self, api_key: Optional[str] = None, model_name: str = "gemini-2.5-flash"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model_name

    def plan_story(
        self,
        fact_pack: FactPack,
        target_duration_sec: float = 55.0,
        tone: str = "curiosity",
        format_type: str = "short",
        archetype: Optional[StoryArchetype] = None,
    ) -> StoryPlan:
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not configured")

        from google import genai
        client = genai.Client(api_key=self.api_key)

        chosen_archetype = archetype or infer_archetype(fact_pack.topic)
        ratios = ARCHETYPE_BEAT_RATIOS.get(chosen_archetype, ARCHETYPE_BEAT_RATIOS[StoryArchetype.PROCESS_EXPLAINER])

        claims_text = "\n".join(
            f"- [{c.source_ref or 'fact'}] {c.claim} (Critical: {c.is_critical})"
            for c in fact_pack.claims
        )

        prompt = f"""
You are the VisionFlow Story Planner. Your mission is to architect a high-retention video narrative structure based STRICTLY on the provided FactPack.
DO NOT write full voiceover script lines. Focus solely on narrative beats, hook mechanism, visual opportunities, and audience promise.

TOPIC: {fact_pack.topic}
ARCHETYPE: {chosen_archetype.value}
RECOMMENDED BEAT RATIOS: {json.dumps(ratios)}
TARGET DURATION: {target_duration_sec} seconds (Format: {format_type})
TONE: {tone}
FACTPACK CLAIMS:
{claims_text}

ENTITIES: {', '.join(fact_pack.entities)}
SUGGESTED ANGLES: {', '.join(fact_pack.suggested_angles)}

RULES:
1. Select the single most compelling narrative angle suited for archetype {chosen_archetype.value}.
2. Formulate a strong audience promise (why the viewer should stay until the last second).
3. Design a hook mechanism fitting the archetype.
4. Break the video into 4 to 6 narrative beats (beat_type: 'hook', 'setup', 'twist', 'development', 'climax', 'payoff_cta').
5. Allocate estimated_duration_sec to each beat respecting the archetype ratios such that the sum approximately equals {target_duration_sec}s.
6. Provide concrete visual_opportunity descriptions for each beat.
7. Specify 2-3 excluded_interpretations (cliches or misleading assumptions to avoid).
8. Return ONLY valid raw JSON adhering to:
{{
  "angle": "chosen angle",
  "audience_promise": "clear benefit to viewer",
  "hook_mechanism": "specific hook strategy",
  "archetype": "{chosen_archetype.value}",
  "beat_ratios": {json.dumps(ratios)},
  "target_duration_sec": {target_duration_sec},
  "tone": "{tone}",
  "excluded_interpretations": ["avoid cliche 1", "avoid trope 2"],
  "beats": [
    {{
      "beat_id": "beat_01",
      "beat_type": "hook",
      "summary": "what happens in this beat",
      "evidence_ref": "reference to a fact or claim",
      "visual_opportunity": "visual elements to depict",
      "estimated_duration_sec": 5.0
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
            return StoryPlan.model_validate(data)
        except Exception as e:
            raise ValueError(f"Gemini story planning failed: {e}") from e


class LocalStoryPlannerProvider(StoryPlannerProvider):
    """
    Deterministic 100% offline rule-based narrative blueprint generator.
    Creates structured narrative beats calibrated to target duration with visual opportunities,
    archetype inference, and dynamic beat ratios.
    """
    def plan_story(
        self,
        fact_pack: FactPack,
        target_duration_sec: float = 55.0,
        tone: str = "curiosity",
        format_type: str = "short",
        archetype: Optional[StoryArchetype] = None,
    ) -> StoryPlan:
        topic = fact_pack.topic
        chosen_archetype = archetype or infer_archetype(topic)
        ratios = ARCHETYPE_BEAT_RATIOS.get(chosen_archetype, ARCHETYPE_BEAT_RATIOS[StoryArchetype.PROCESS_EXPLAINER])

        # Dynamic angle and hook mechanism based on archetype
        if chosen_archetype == StoryArchetype.MYSTERY:
            primary_angle = f"Bí ẩn chưa có lời giải đằng sau {topic}"
            hook_mechanism = "Mở đầu bằng câu hỏi nghịch lý gây hoang mang kích thích trí tò mò tuyệt đối."
            audience_promise = f"Giải mã bí ẩn lớn nhất của {topic} chỉ trong {int(target_duration_sec)} giây."
        elif chosen_archetype == StoryArchetype.TRANSFORMATION:
            primary_angle = f"Sự lột xác kỳ diệu: Hành trình tái sinh của {topic}"
            hook_mechanism = "Đối lập mạnh mẽ giữa điểm khởi đầu thô ráp và thành quả ngoạn mục."
            audience_promise = f"Chứng kiến từng khoảnh khắc biến đổi ngoạn mục của {topic} trong {int(target_duration_sec)} giây."
        elif chosen_archetype == StoryArchetype.TIMELINE:
            primary_angle = f"Dòng thời gian phát triển và bước ngoặt lịch sử của {topic}"
            hook_mechanism = "Điểm xuất phát khiêm tốn đối chiếu với vị thế hiện tại."
            audience_promise = f"Lướt qua toàn bộ lịch sử thăng trầm của {topic} trong {int(target_duration_sec)} giây."
        elif chosen_archetype == StoryArchetype.CAUSE_EFFECT:
            primary_angle = f"Hiệu ứng dây chuyền: Nguyên nhân sâu xa tạo nên {topic}"
            hook_mechanism = "Một tác động nhỏ dẫn đến hậu quả khổng lồ không thể đảo ngược."
            audience_promise = f"Hiểu thấu chuỗi nguyên nhân - kết quả định hình nên {topic} trong {int(target_duration_sec)} giây."
        elif chosen_archetype == StoryArchetype.COMPARISON:
            primary_angle = f"Đối đầu kinh điển: Đâu là sự thật phân định về {topic}?"
            hook_mechanism = "Đặt hai quan điểm hoặc phương pháp tương phản cạnh nhau."
            audience_promise = f"Tìm ra câu trả lời chính xác nhất khi so sánh {topic} trong {int(target_duration_sec)} giây."
        elif chosen_archetype == StoryArchetype.INVESTIGATION:
            primary_angle = f"Điều tra đa chiều: Vén màn sự thật về {topic}"
            hook_mechanism = "Lần theo các manh mối và bằng chứng bị bỏ quên."
            audience_promise = f"Đưa ra ánh sáng toàn bộ sự thật về {topic} trong {int(target_duration_sec)} giây."
        elif chosen_archetype == StoryArchetype.DISCOVERY:
            primary_angle = f"Khám phá chân trời mới: Những phát hiện kinh ngạc về {topic}"
            hook_mechanism = "Một phát hiện mang tính đột phá làm thay đổi góc nhìn."
            audience_promise = f"Khám phá những điều chưa từng được tiết lộ về {topic} trong {int(target_duration_sec)} giây."
        else:  # PROCESS_EXPLAINER
            primary_angle = (
                fact_pack.suggested_angles[0]
                if fact_pack.suggested_angles
                else f"Bí quyết và quy trình tinh hoa tạo nên {topic}"
            )
            hook_mechanism = "Đặt ra chi tiết kỹ thuật ấn tượng khiến người xem muốn xem trọn quy trình."
            audience_promise = f"Khám phá toàn bộ quy trình chuẩn mực của {topic} chỉ trong {int(target_duration_sec)} giây."

        # Calibrate beat durations dynamically using archetype ratios
        r_hook = ratios.get("hook", 0.10)
        r_setup = ratios.get("setup", 0.15)
        r_dev = ratios.get("development", 0.40)
        r_climax = ratios.get("climax", 0.25)

        dur_hook = round(target_duration_sec * r_hook, 1)
        dur_setup = round(target_duration_sec * r_setup, 1)
        dur_dev = round(target_duration_sec * r_dev, 1)
        dur_climax = round(target_duration_sec * r_climax, 1)
        dur_cta = round(target_duration_sec - (dur_hook + dur_setup + dur_dev + dur_climax), 1)

        # Build archetype-specific beats
        beats: List[NarrativeBeat] = [
            NarrativeBeat(
                beat_id="beat_01_hook",
                beat_type="hook",
                summary=f"Mở đầu bằng hook đặc trưng của archetype {chosen_archetype.value}: {hook_mechanism}",
                evidence_ref=fact_pack.claims[0].claim if fact_pack.claims else "topic_premise",
                visual_opportunity=f"Cảnh cận cảnh hành động nhanh, chi tiết ấn tượng nhất của {topic}.",
                estimated_duration_sec=max(3.5, dur_hook),
            ),
            NarrativeBeat(
                beat_id="beat_02_setup",
                beat_type="setup",
                summary=f"Thiết lập bối cảnh {chosen_archetype.value}, giới thiệu đối tượng và thách thức cốt lõi.",
                evidence_ref="workflow_materials",
                visual_opportunity="Góc quay trung toàn cảnh xưởng làm việc hoặc không gian chuẩn bị tỉ mỉ.",
                estimated_duration_sec=max(3.0, dur_setup),
            ),
            NarrativeBeat(
                beat_id="beat_03_development",
                beat_type="development",
                summary=f"Khai triển diễn biến chính của {chosen_archetype.value} với chuỗi hành động chuyên môn.",
                evidence_ref=fact_pack.claims[1].claim if len(fact_pack.claims) > 1 else "technical_precision",
                visual_opportunity="Macro cực cận thao tác bàn tay khéo léo hoặc công cụ chuyên dụng vận hành.",
                estimated_duration_sec=max(5.0, dur_dev),
            ),
            NarrativeBeat(
                beat_id="beat_04_climax",
                beat_type="climax",
                summary=f"Cao trào bùng nổ theo mô thức {chosen_archetype.value}, giải tỏa căng thẳng hoặc công bố thành quả.",
                evidence_ref="transformation_peak",
                visual_opportunity="Cảnh quay chuyển động mượt mà phô diễn thành phẩm sắc nét dưới ánh sáng tự nhiên.",
                estimated_duration_sec=max(4.0, dur_climax),
            ),
            NarrativeBeat(
                beat_id="beat_05_cta",
                beat_type="payoff_cta",
                summary="Tổng kết thông điệp sâu sắc và lời kêu gọi tương tác tự nhiên.",
                evidence_ref="conclusion_takeaway",
                visual_opportunity="Góc nhìn toàn cảnh hoàn chỉnh và khung hình kết ấn tượng.",
                estimated_duration_sec=max(3.0, dur_cta),
            ),
        ]

        excluded_interpretations = [
            "Không biến video thành bài giảng lý thuyết khô khan.",
            "Không lạm dụng các sáo ngữ giật gân vô căn cứ.",
            "Tránh miêu tả hời hợt bề mặt mà bỏ qua chi tiết kỹ thuật tinh tế.",
        ]

        return StoryPlan(
            angle=primary_angle,
            audience_promise=audience_promise,
            hook_mechanism=hook_mechanism,
            archetype=chosen_archetype,
            beat_ratios=ratios,
            beats=beats,
            excluded_interpretations=excluded_interpretations,
            target_duration_sec=target_duration_sec,
            tone=tone,
        )


# ---------------------------------------------------------------------------
# Story Planner Service
# ---------------------------------------------------------------------------

class StoryPlanner:
    def __init__(self, provider: Optional[StoryPlannerProvider] = None):
        if provider is not None:
            self.provider = provider
        elif os.getenv("GEMINI_API_KEY"):
            self.provider = GeminiStoryPlannerProvider()
        else:
            self.provider = LocalStoryPlannerProvider()

        self.local_fallback = LocalStoryPlannerProvider()

    def generate_story_plan(
        self,
        fact_pack: FactPack,
        target_duration_sec: float = 55.0,
        tone: str = "curiosity",
        format_type: str = "short",
        archetype: Optional[StoryArchetype] = None,
    ) -> StoryPlan:
        try:
            return self.provider.plan_story(
                fact_pack=fact_pack,
                target_duration_sec=target_duration_sec,
                tone=tone,
                format_type=format_type,
                archetype=archetype,
            )
        except Exception as e:
            logger.warning(f"Primary story planner provider failed ({e}). Using local fallback.")
            return self.local_fallback.plan_story(
                fact_pack=fact_pack,
                target_duration_sec=target_duration_sec,
                tone=tone,
                format_type=format_type,
                archetype=archetype,
            )


story_planner = StoryPlanner()
