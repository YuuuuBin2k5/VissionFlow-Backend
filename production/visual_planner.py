"""
Visual Planner Service (Phase 4 - Section 2, 3, 4, 5, 6)
Transforms canonical SceneNarration and narrative context into high-fidelity VisualIntents.
DECIDES: "What does the audience need to see during this narration segment?"
DOES NOT: Select file paths or URLs (reserved for Asset Resolver and Editor Planner).
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from production.contracts import (
    FactPack,
    NarrativeBeat,
    SceneNarration,
    ScriptPlan,
    StoryPlan,
    VisualIntent,
    VisualPlan,
    VisualRole,
)
from production.embedding_service import VietnameseQueryTranslationBridge

logger = logging.getLogger(__name__)

# Stopwords & overly abstract tokens to avoid in canonical search_query_en
GENERIC_QUERY_STOPWORDS = {
    "mystery", "life", "emotion", "emotions", "human", "history", "dark",
    "people", "world", "time", "things", "feeling", "feelings", "story",
    "concept", "deep", "vibe", "vibes", "energy", "atmosphere", "mood",
    "background", "scene", "video", "footage", "cinematic", "4k", "hd",
    "chúng", "ta", "của", "và", "những", "các", "một", "trong", "được",
    "đến", "với", "cho", "về", "có", "là", "khi", "tại", "này", "đó"
}

# Domain English visual mapping for crafts, tech, and natural phenomena
CRAFT_VISUAL_MAP: Dict[str, Dict[str, Any]] = {
    "đũa tre": {
        "subject": "bamboo chopsticks",
        "action": "shaping carving polishing",
        "setting": "traditional workshop",
        "must_show": ["bamboo wood", "artisan hands"],
        "must_avoid": ["plastic chopsticks", "metal factory"],
    },
    "tre": {
        "subject": "bamboo chopsticks",
        "action": "shaping carving polishing",
        "setting": "traditional workshop",
        "must_show": ["bamboo wood", "artisan hands"],
        "must_avoid": ["plastic chopsticks", "metal factory"],
    },
    "đũa": {
        "subject": "bamboo chopsticks",
        "action": "shaping carving polishing",
        "setting": "traditional workshop",
        "must_show": ["bamboo wood", "artisan hands"],
        "must_avoid": ["plastic chopsticks", "metal factory"],
    },
    "mộng gỗ": {
        "subject": "wood joinery mortise tenon",
        "action": "interlocking chiseling fitting",
        "setting": "carpentry workshop",
        "must_show": ["wooden joint interlocking", "chisel woodwork"],
        "must_avoid": ["metal screws", "nails", "glue"],
    },
    "mộng": {
        "subject": "wood joinery mortise tenon",
        "action": "interlocking chiseling fitting",
        "setting": "carpentry workshop",
        "must_show": ["wooden joint interlocking", "chisel woodwork"],
        "must_avoid": ["metal screws", "nails", "glue"],
    },
    "thợ mộc": {
        "subject": "wood joinery mortise tenon",
        "action": "interlocking chiseling fitting",
        "setting": "carpentry workshop",
        "must_show": ["wooden joint interlocking", "chisel woodwork"],
        "must_avoid": ["metal screws", "nails", "glue"],
    },
    "rèn kiếm": {
        "subject": "katana sword blade",
        "action": "blacksmith forging glowing steel hammering",
        "setting": "forge smithy",
        "must_show": ["red glowing metal", "hammer striking anvil", "sparks"],
        "must_avoid": ["modern laser cutter", "unrelated kitchen knife"],
    },
    "kiếm": {
        "subject": "katana sword blade",
        "action": "blacksmith forging glowing steel hammering",
        "setting": "forge smithy",
        "must_show": ["red glowing metal", "hammer striking anvil", "sparks"],
        "must_avoid": ["modern laser cutter", "unrelated kitchen knife"],
    },
    "thợ rèn": {
        "subject": "katana sword blade",
        "action": "blacksmith forging glowing steel hammering",
        "setting": "forge smithy",
        "must_show": ["red glowing metal", "hammer striking anvil", "sparks"],
        "must_avoid": ["modern laser cutter", "unrelated kitchen knife"],
    },
    "lưỡi thép": {
        "subject": "katana sword blade",
        "action": "blacksmith forging glowing steel hammering",
        "setting": "forge smithy",
        "must_show": ["red glowing metal", "hammer striking anvil", "sparks"],
        "must_avoid": ["modern laser cutter", "unrelated kitchen knife"],
    },
    "vi mạch": {
        "subject": "semiconductor microchip wafer",
        "action": "automated robotic etching photolithography",
        "setting": "cleanroom laboratory",
        "must_show": ["silicon wafer", "cleanroom bunny suit technician", "robotic arm"],
        "must_avoid": ["messy electronics repair", "soldering iron"],
    },
    "bán dẫn": {
        "subject": "silicon semiconductor chip",
        "action": "nanometer wafer manufacturing",
        "setting": "high tech cleanroom fab",
        "must_show": ["silicon wafer disk", "cleanroom robotics"],
        "must_avoid": ["computer motherboard dust"],
    },
    "phòng sạch": {
        "subject": "semiconductor microchip wafer",
        "action": "automated robotic etching photolithography",
        "setting": "cleanroom laboratory",
        "must_show": ["silicon wafer", "cleanroom robotics"],
        "must_avoid": ["messy electronics repair", "soldering iron"],
    },
    "wafer": {
        "subject": "semiconductor microchip wafer",
        "action": "automated robotic etching photolithography",
        "setting": "cleanroom laboratory",
        "must_show": ["silicon wafer", "cleanroom robotics"],
        "must_avoid": ["soldering iron"],
    },
    "quang khắc": {
        "subject": "semiconductor microchip wafer",
        "action": "automated robotic etching photolithography",
        "setting": "cleanroom laboratory",
        "must_show": ["silicon wafer", "cleanroom robotics"],
        "must_avoid": ["soldering iron"],
    },
    "đồng hồ": {
        "subject": "luxury mechanical watch movement",
        "action": "watchmaker assembling tourbillon gears tweezers",
        "setting": "watchmaker atelier",
        "must_show": ["micro gears ticking", "precision tweezers"],
        "must_avoid": ["digital smartwatch", "wall clock"],
    },
    "bánh răng": {
        "subject": "luxury mechanical watch movement",
        "action": "watchmaker assembling tourbillon gears tweezers",
        "setting": "watchmaker atelier",
        "must_show": ["micro gears ticking", "precision tweezers"],
        "must_avoid": ["digital smartwatch", "wall clock"],
    },
    "gốm": {
        "subject": "ceramic clay pottery",
        "action": "potter hands spinning pottery wheel sculpting",
        "setting": "pottery studio",
        "must_show": ["wet clay spinning wheel", "artisan hands shaping"],
        "must_avoid": ["industrial plastic molding"],
    },
    "đất sét": {
        "subject": "ceramic clay pottery",
        "action": "potter hands spinning pottery wheel sculpting",
        "setting": "pottery studio",
        "must_show": ["wet clay spinning wheel", "artisan hands shaping"],
        "must_avoid": ["industrial plastic molding"],
    },
    "bàn xoay": {
        "subject": "ceramic clay pottery",
        "action": "potter hands spinning pottery wheel sculpting",
        "setting": "pottery studio",
        "must_show": ["wet clay spinning wheel", "artisan hands shaping"],
        "must_avoid": ["industrial plastic molding"],
    },
    "thác nước": {
        "subject": "waterfall cascading river",
        "action": "powerful water flowing misty torrent",
        "setting": "mountain valley forest",
        "must_show": ["rushing water spray", "lush green canyon"],
        "must_avoid": ["dry riverbed", "city canal"],
    },
    "thác": {
        "subject": "waterfall cascading river",
        "action": "powerful water flowing misty torrent",
        "setting": "mountain valley forest",
        "must_show": ["rushing water spray", "lush green canyon"],
        "must_avoid": ["dry riverbed", "city canal"],
    },
    "lâu đài": {
        "subject": "historical ancient castle stone architecture",
        "action": "standing resilient hill monument",
        "setting": "historic hill valley",
        "must_show": ["ancient stone castle walls", "stone masonry"],
        "must_avoid": ["modern glass skyscraper"],
    },
    "pháo đài": {
        "subject": "historical ancient castle stone architecture",
        "action": "standing resilient hill monument",
        "setting": "historic hill valley",
        "must_show": ["ancient stone castle walls", "stone masonry"],
        "must_avoid": ["modern glass skyscraper"],
    },
    "thành cổ": {
        "subject": "historical ancient castle stone architecture",
        "action": "standing resilient hill monument",
        "setting": "historic hill valley",
        "must_show": ["ancient stone castle walls", "stone masonry"],
        "must_avoid": ["modern glass skyscraper"],
    },
    "thành phố": {
        "subject": "modern cyberpunk neon city traffic timelapse",
        "action": "traffic rushing night skyline timelapse",
        "setting": "modern metropolis night",
        "must_show": ["neon illumination", "night skyline"],
        "must_avoid": ["countryside field"],
    },
    "neon": {
        "subject": "modern cyberpunk neon city traffic timelapse",
        "action": "traffic rushing night skyline timelapse",
        "setting": "modern metropolis night",
        "must_show": ["neon illumination", "night skyline"],
        "must_avoid": ["countryside field"],
    },
    "xe cộ": {
        "subject": "modern cyberpunk neon city traffic timelapse",
        "action": "traffic rushing night skyline timelapse",
        "setting": "modern metropolis night",
        "must_show": ["neon illumination", "traffic light trails"],
        "must_avoid": ["countryside field"],
    },
    "cao tốc": {
        "subject": "modern cyberpunk neon city traffic timelapse",
        "action": "traffic rushing night skyline timelapse",
        "setting": "modern metropolis night",
        "must_show": ["neon illumination", "traffic light trails"],
        "must_avoid": ["countryside field"],
    },
    "biển": {
        "subject": "deep ocean waves atmospheric surface",
        "action": "rolling waves crashing turquoise water",
        "setting": "open sea ocean",
        "must_show": ["ocean waves rolling", "deep blue horizon"],
        "must_avoid": ["swimming pool", "city lake"],
    },
    "đại dương": {
        "subject": "deep ocean waves atmospheric surface",
        "action": "rolling waves crashing turquoise water",
        "setting": "open sea ocean",
        "must_show": ["ocean waves rolling", "deep blue horizon"],
        "must_avoid": ["swimming pool", "city lake"],
    },
    "sóng biển": {
        "subject": "deep ocean waves atmospheric surface",
        "action": "rolling waves crashing turquoise water",
        "setting": "open sea ocean",
        "must_show": ["ocean waves rolling", "deep blue horizon"],
        "must_avoid": ["swimming pool", "city lake"],
    },
    "sóng": {
        "subject": "deep ocean waves atmospheric surface",
        "action": "rolling waves crashing turquoise water",
        "setting": "open sea ocean",
        "must_show": ["ocean waves rolling", "deep blue horizon"],
        "must_avoid": ["swimming pool", "city lake"],
    },
    "robot": {
        "subject": "industrial robotic arm",
        "action": "automated robotic arm assembling precision",
        "setting": "smart automated factory",
        "must_show": ["robotic arm welding or assembling", "automation"],
        "must_avoid": ["human manual labor with hand tools"],
    },
}


class VisualPlannerProvider(ABC):
    @abstractmethod
    def plan_visuals(
        self,
        script_plan: ScriptPlan,
        story_plan: Optional[StoryPlan] = None,
        fact_pack: Optional[FactPack] = None,
        channel_profile: Optional[Dict[str, Any]] = None,
        available_sources: Optional[List[Any]] = None,
    ) -> VisualPlan:
        pass


class LocalVisualPlannerProvider(VisualPlannerProvider):
    """
    Deterministic rule & NLP-based Visual Planner.
    Extracts semantic concepts, translates to canonical English, modulates roles,
    and partitions multi-shot sequences without network dependencies.
    """

    def plan_visuals(
        self,
        script_plan: ScriptPlan,
        story_plan: Optional[StoryPlan] = None,
        fact_pack: Optional[FactPack] = None,
        channel_profile: Optional[Dict[str, Any]] = None,
        available_sources: Optional[List[Any]] = None,
    ) -> VisualPlan:
        plan_id = f"vp_{uuid.uuid4().hex[:8]}"
        all_intents: List[VisualIntent] = []
        total_scenes = len(script_plan.scenes)

        topic = fact_pack.topic if fact_pack and fact_pack.topic else script_plan.title

        for idx, scene in enumerate(script_plan.scenes):
            scene_id = scene.scene_id or f"scene_{scene.scene_index:03d}"
            dur = scene.estimated_speech_duration_sec or 4.5
            is_hook_scene = (idx == 0 and total_scenes > 1)
            is_final_scene = (idx == total_scenes - 1 and total_scenes > 1)

            # Base concept translation & role inference
            raw_content = f"{scene.visual_cue or ''} {scene.narration}".strip()
            visual_profile = self._extract_visual_profile(raw_content, topic)
            primary_role = self._infer_single_role(idx, total_scenes, raw_content)

            # Determine whether multi-shot partitioning is required
            # Multi-shot if duration > 4.2s or hook scene in multi-scene video
            needs_multi_shot = (dur > 4.2) or is_hook_scene
            shot_count = 3 if dur >= 7.0 else (2 if needs_multi_shot else 1)

            if shot_count == 1:
                intent = self._build_intent(
                    scene_id=scene_id,
                    shot_order=1,
                    role=primary_role,
                    profile=visual_profile,
                    fact_refs=scene.fact_refs,
                    duration_weight=1.0,
                    importance=1.0 if is_hook_scene or is_final_scene else 0.85,
                )
                all_intents.append(intent)
            else:
                # Multi-shot progression:
                if total_scenes == 1:
                    # Single scene query: primary role gets priority in Shot 1
                    sec_role = VisualRole.DETAIL if primary_role != VisualRole.DETAIL else VisualRole.PROCESS
                    third_role = VisualRole.PROCESS if primary_role not in (VisualRole.PROCESS, VisualRole.DETAIL) else VisualRole.ESTABLISHING
                    roles = [primary_role, sec_role] if shot_count == 2 else [primary_role, sec_role, third_role]
                elif is_hook_scene:
                    roles = [VisualRole.HOOK, VisualRole.ESTABLISHING] if shot_count == 2 else [VisualRole.HOOK, VisualRole.ESTABLISHING, VisualRole.DETAIL]
                elif is_final_scene:
                    roles = [VisualRole.REVEAL, VisualRole.RESET] if shot_count == 2 else [VisualRole.PROCESS, VisualRole.REVEAL, VisualRole.RESET]
                else:
                    roles = [VisualRole.ESTABLISHING, VisualRole.PROCESS] if shot_count == 2 else [VisualRole.ESTABLISHING, VisualRole.PROCESS, VisualRole.DETAIL]

                weights = [0.5, 0.5] if shot_count == 2 else [0.4, 0.4, 0.2]

                for s_idx, (r, w) in enumerate(zip(roles, weights)):
                    intent = self._build_intent(
                        scene_id=scene_id,
                        shot_order=s_idx + 1,
                        role=r,
                        profile=visual_profile,
                        fact_refs=scene.fact_refs,
                        duration_weight=w,
                        importance=1.0 if r in (VisualRole.HOOK, VisualRole.REVEAL) else 0.85,
                    )
                    all_intents.append(intent)

        has_generic = any(getattr(intent, "_mode", None) == "GENERIC_FALLBACK" or (intent.description and "workshop studio line" in intent.description) for intent in all_intents)
        planner_mode = "GENERIC_FALLBACK" if has_generic else "LOCAL_DOMAIN_RULES"
        warnings = ["Visual planner degraded: generic fallback was used for 1 or more scenes lacking cataloged craft domain terms."] if has_generic else []

        return VisualPlan(
            plan_id=plan_id,
            title=script_plan.title,
            intents=all_intents,
            planner_mode=planner_mode,
            warnings=warnings,
            created_at=datetime.now(timezone.utc),
        )

    def _infer_single_role(self, idx: int, total: int, content: str) -> VisualRole:
        c = content.lower()
        if any(k in c for k in ["cận cảnh", "chi tiết", "từng chiếc", "từng góc", "từng thanh", "từng nan", "từng bánh", "từng đợt", "từng kẽ", "từng phiến", "từng milimet", "nhíp", "chuốt", "đục", "mài", "siêu nhỏ", "macro", "nan tre", "khớp mộng", "khít khao", "nhỏ"]):
            return VisualRole.DETAIL
        if any(k in c for k in ["toàn cảnh", "hùng vĩ", "sừng sững", "pháo đài", "thành cổ", "lâu đài", "vách núi", "thung lũng", "đại dương", "mênh mông", "biển", "rừng đại ngàn", "vách đá"]):
            return VisualRole.ESTABLISHING
        if any(k in c for k in ["rực đỏ", "vun vút", "tia lửa", "đập chan chát", "búa tạ", "nửa đêm", "sống kiếm", "neon", "ánh đèn pha", "pha ô tô", "khám phá bí mật"]):
            return VisualRole.HOOK
        if any(k in c for k in ["bằng chứng", "chứng minh", "sự thật", "dẫn chứng", "nguyên nhân"]):
            return VisualRole.EVIDENCE
        if any(k in c for k in ["so sánh", "ngược lại", "đối đầu", "khác biệt"]):
            return VisualRole.CONTRAST
        if any(k in c for k in ["bất ngờ", "vén màn", "tiết lộ", "kết quả"]):
            return VisualRole.REVEAL
        if any(k in c for k in ["bàn xoay", "quang khắc", "tự động", "dây chuyền", "lắp ghép", "chế tạo", "tạo hình", "ghép mộng", "đan chặt", "uốn", "rèn", "vuốt", "đổ ầm ầm", "nặn", "gọt"]):
            return VisualRole.PROCESS
        if idx == 0 and total > 1:
            return VisualRole.HOOK
        if idx == total - 1 and total > 1:
            return VisualRole.RESET
        return VisualRole.PROCESS

    def _extract_visual_profile(self, text: str, topic: str) -> Dict[str, Any]:
        combined = f"{text} {topic}".lower()

        # 1. Match known domain craft templates (sorted by key length descending)
        sorted_craft_keys = sorted(CRAFT_VISUAL_MAP.keys(), key=len, reverse=True)
        for key in sorted_craft_keys:
            if key in combined:
                template = CRAFT_VISUAL_MAP[key]
                return {
                    "subject": template["subject"],
                    "action": template["action"],
                    "setting": template["setting"],
                    "must_show": list(template["must_show"]),
                    "must_avoid": list(template["must_avoid"]),
                    "mode": "LOCAL_DOMAIN_RULES",
                }

        # 2. General Concept Map Matching
        matched_en_terms = []
        is_generic_fallback = False
        for vi_kw, en_syns in VietnameseQueryTranslationBridge.CONCEPT_MAP.items():
            if vi_kw in combined:
                primary_word = en_syns.split()[0]
                matched_en_terms.append(primary_word)

        if not matched_en_terms:
            # Fallback normalize
            is_generic_fallback = True
            norm, _, trans = VietnameseQueryTranslationBridge.translate_and_enrich(text[:100])
            target_text = trans or norm or ""
            matched_en_terms = [w for w in target_text.split() if w.lower() not in GENERIC_QUERY_STOPWORDS][:4]

        subject_cand = matched_en_terms[:2] if len(matched_en_terms) >= 2 else matched_en_terms or ["craft", "process"]
        action_cand = matched_en_terms[2:4] if len(matched_en_terms) >= 4 else ["making", "precision"]

        return {
            "subject": " ".join(subject_cand),
            "action": " ".join(action_cand),
            "setting": "workshop studio line",
            "must_show": subject_cand,
            "must_avoid": ["unrelated generic stock"],
            "mode": "GENERIC_FALLBACK" if is_generic_fallback else "LOCAL_DOMAIN_RULES",
        }

    def _build_intent(
        self,
        scene_id: str,
        shot_order: int,
        role: VisualRole,
        profile: Dict[str, Any],
        fact_refs: List[str],
        duration_weight: float,
        importance: float,
    ) -> VisualIntent:
        subj = profile["subject"]
        act = profile["action"]
        setting = profile["setting"]

        # Formulate concise canonical English search query (3-5 words)
        if role == VisualRole.HOOK:
            query_en = f"{subj} {act} dynamic"
            shot_prefs = ["close_up", "dramatic_angle"]
            motion = "active"
            desc = f"High-impact visual hook showing {subj} {act} with energetic movement"
        elif role == VisualRole.ESTABLISHING:
            query_en = f"{subj} {setting} wide"
            shot_prefs = ["wide", "medium_wide"]
            motion = "subtle"
            desc = f"Wide establishing overview of {subj} inside {setting}"
        elif role == VisualRole.DETAIL:
            query_en = f"{subj} macro close up"
            shot_prefs = ["extreme_close_up", "close_up"]
            motion = "subtle"
            desc = f"Extreme macro detail showing the precision texture of {subj}"
        elif role == VisualRole.EVIDENCE:
            query_en = f"{subj} {act} evidence real"
            shot_prefs = ["medium_close_up", "close_up"]
            motion = "active"
            desc = f"Factual evidentiary footage demonstrating {subj} {act}"
        elif role == VisualRole.CONTRAST:
            query_en = f"{subj} contrast comparison"
            shot_prefs = ["medium"]
            motion = "active"
            desc = f"Visual contrast highlighting differing aspects of {subj}"
        elif role == VisualRole.REVEAL:
            query_en = f"{subj} finished reveal"
            shot_prefs = ["medium_close_up", "hero_shot"]
            motion = "dynamic"
            desc = f"Dramatic reveal of the final completed {subj}"
        elif role == VisualRole.RESET:
            query_en = f"{subj} {setting} ambient"
            shot_prefs = ["medium", "wide"]
            motion = "subtle"
            desc = f"Calm ambient visual concluding the segment on {subj}"
        else:  # PROCESS
            query_en = f"{subj} {act} {setting}"
            shot_prefs = ["medium", "medium_close_up"]
            motion = "active"
            desc = f"Active step-by-step process of {subj} {act} in {setting}"

        # Clean query: Remove stop/generic words and enforce length
        clean_tokens = [
            w for w in re.findall(r"\w+", query_en.lower())
            if w not in GENERIC_QUERY_STOPWORDS and len(w) > 2
        ]
        if len(clean_tokens) < 2:
            clean_tokens.extend(["craft", "workshop"])
        canonical_query = " ".join(clean_tokens[:5])

        subjects_list = [w for w in subj.split() if w not in GENERIC_QUERY_STOPWORDS]
        actions_list = [w for w in act.split() if w not in GENERIC_QUERY_STOPWORDS]

        return VisualIntent(
            id=f"vi_{scene_id}_{shot_order}_{uuid.uuid4().hex[:4]}",
            scene_id=scene_id,
            shot_order=shot_order,
            visual_role=role.value,
            description=desc,
            search_query_en=canonical_query,
            subjects=subjects_list or [subj],
            actions=actions_list or [act],
            setting=setting,
            shot_preferences=shot_prefs,
            motion_preference=motion,
            must_show=profile.get("must_show", subjects_list),
            must_avoid=profile.get("must_avoid", ["unrelated"]),
            fact_refs=fact_refs,
            importance=importance,
            duration_weight=duration_weight,
        )


class GeminiVisualPlannerProvider(VisualPlannerProvider):
    """
    Cloud LLM Visual Planner utilizing Google GenAI SDK.
    Emits structured VisualPlan schemas and falls back to LocalVisualPlannerProvider on failure.
    """

    def __init__(self, api_key: Optional[str] = None, model_name: str = "gemini-2.5-flash"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model_name
        self.fallback = LocalVisualPlannerProvider()

    def plan_visuals(
        self,
        script_plan: ScriptPlan,
        story_plan: Optional[StoryPlan] = None,
        fact_pack: Optional[FactPack] = None,
        channel_profile: Optional[Dict[str, Any]] = None,
        available_sources: Optional[List[Any]] = None,
    ) -> VisualPlan:
        if not self.api_key:
            return self.fallback.plan_visuals(script_plan, story_plan, fact_pack, channel_profile, available_sources)

        try:
            from google import genai
            client = genai.Client(api_key=self.api_key)

            scenes_brief = []
            for scn in script_plan.scenes:
                scenes_brief.append({
                    "scene_id": scn.scene_id or f"scene_{scn.scene_index:03d}",
                    "index": scn.scene_index,
                    "narration": scn.narration,
                    "visual_cue": scn.visual_cue,
                    "fact_refs": scn.fact_refs,
                    "estimated_sec": scn.estimated_speech_duration_sec,
                })

            prompt = f"""
You are the VisionFlow Visual Planner.
TASK: Translate each scene narration into 1 to 3 distinct VisualIntents (multi-shot if duration > 4.2s).
RULES:
1. NEVER select file paths, URLs, or specific camera models. Only describe what the viewer needs to see.
2. Output canonical English search queries ('search_query_en') using 3-5 specific keywords (subjects + actions + setting).
3. Do NOT include generic filler words ("cinematic", "mystery", "life", "emotion", "4k").
4. Assign visual roles: HOOK, ESTABLISHING, PROCESS, DETAIL, EVIDENCE, CONTRAST, REVEAL, RESET.
5. Return ONLY a valid JSON object matching the schema:
{{
  "intents": [
    {{
      "scene_id": "scene_001",
      "shot_order": 1,
      "visual_role": "HOOK",
      "description": "...",
      "search_query_en": "bamboo cutting machine factory",
      "subjects": ["bamboo", "cutting machine"],
      "actions": ["feeding bamboo", "cutting"],
      "setting": "factory production line",
      "shot_preferences": ["close_up", "medium_close_up"],
      "motion_preference": "active",
      "must_show": ["bamboo", "machine blade"],
      "must_avoid": ["finished chopsticks only"],
      "fact_refs": ["fact_001"],
      "importance": 1.0,
      "duration_weight": 0.5
    }}
  ]
}}

SCENES:
{json.dumps(scenes_brief, ensure_ascii=False, indent=2)}
"""
            resp = client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config={"response_mime_type": "application/json"}
            )
            raw_text = resp.text.strip()
            data = json.loads(raw_text)
            raw_intents = data.get("intents", [])

            intents = []
            for item in raw_intents:
                intent_obj = VisualIntent(**item)
                intents.append(intent_obj)

            if intents:
                return VisualPlan(
                    plan_id=f"vp_{uuid.uuid4().hex[:8]}",
                    title=script_plan.title,
                    intents=intents,
                    planner_mode="CLOUD_SEMANTIC",
                    created_at=datetime.now(timezone.utc),
                )
        except Exception as e:
            logger.warning(f"Gemini Visual Planner failed: {e}. Falling back to LocalVisualPlanner.")

        fallback_plan = self.fallback.plan_visuals(script_plan, story_plan, fact_pack, channel_profile, available_sources)
        fallback_plan.warnings.append(f"Gemini Cloud Visual Planner fallback used.")
        return fallback_plan


class VisualPlanner:
    """
    Main Visual Planner entry point.
    Coordinates local and cloud providers with fallback tolerance.
    """
    def __init__(self, provider: Optional[VisualPlannerProvider] = None):
        if provider is not None:
            self.provider = provider
        elif os.getenv("GEMINI_API_KEY") and os.getenv("VISIONFLOW_USE_DEV_REPOSITORIES") != "1":
            self.provider = GeminiVisualPlannerProvider()
        else:
            self.provider = LocalVisualPlannerProvider()

    def generate_visual_plan(
        self,
        script_plan: ScriptPlan,
        story_plan: Optional[StoryPlan] = None,
        fact_pack: Optional[FactPack] = None,
        channel_profile: Optional[Dict[str, Any]] = None,
        available_sources: Optional[List[Any]] = None,
        run_id: Optional[str] = None,
    ) -> VisualPlan:
        plan = self.provider.plan_visuals(
            script_plan=script_plan,
            story_plan=story_plan,
            fact_pack=fact_pack,
            channel_profile=channel_profile,
            available_sources=available_sources,
        )
        if run_id:
            plan.run_id = run_id
        return plan


visual_planner = VisualPlanner()
