"""
Input Normalizer for VisionFlow Auto Production System (Phase 1 & Phase 3.5 Hardening)
Transforms messy raw operator input (text, links, uploaded files, raw scripts, developer JSON)
into canonical AutoVideoRequest with strict security controls for:
- AUTO: Instruction/Sources -> Research -> Story -> Script -> Quality Gate
- SCRIPT: Plain text voiceover parsing into ScriptPlan with stage skipping
- JSON: Structured developer payload validation, size limits (<1MB), and path traversal protection
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, List, Optional

from production.contracts import (
    AutoVideoRequest,
    EditorPlan,
    InputMode,
    ProductionFormat,
    ReviewMode,
    RightsState,
    RunEnvironment,
    SceneNarration,
    ScriptPlan,
    SourceInput,
    SourceKind,
)
from production.config_loader import config_loader

MAX_JSON_PAYLOAD_BYTES = 1_048_576  # 1 MB security limit


# ---------------------------------------------------------------------------
# SCRIPT Parser
# ---------------------------------------------------------------------------

class ScriptParser:
    """
    Parses raw human or operator voiceover scripts into structured ScriptPlan & SceneNarration.
    """
    @staticmethod
    def parse(raw_text: str, default_title: Optional[str] = None, target_wps: float = 2.8) -> ScriptPlan:
        cleaned = raw_text.strip()
        if not cleaned:
            raise ValueError("Raw script text cannot be empty.")

        # Split into blocks by double newlines or paragraph breaks
        blocks = [b.strip() for b in re.split(r"\n\s*\n+", cleaned) if b.strip()]

        # If only one large paragraph, split intelligently by sentences
        if len(blocks) == 1:
            sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", blocks[0]) if s.strip()]
            scenes_text = []
            curr_chunk = []
            curr_words = 0
            for sent in sentences:
                w_count = len(re.findall(r"\w+", sent))
                if curr_words + w_count > 35 and curr_chunk:
                    scenes_text.append(" ".join(curr_chunk))
                    curr_chunk = [sent]
                    curr_words = w_count
                else:
                    curr_chunk.append(sent)
                    curr_words += w_count
            if curr_chunk:
                scenes_text.append(" ".join(curr_chunk))
        else:
            scenes_text = blocks

        scenes: List[SceneNarration] = []
        for idx, text in enumerate(scenes_text):
            w_count = len(re.findall(r"\w+", text))
            est_dur = round(w_count / target_wps, 2) if target_wps > 0 else 0.0
            beat_role = "hook" if idx == 0 else ("payoff_cta" if idx == len(scenes_text) - 1 else "development")
            scenes.append(
                SceneNarration(
                    scene_id=f"scene_{idx + 1}",
                    scene_index=idx + 1,
                    narration=text,
                    beat_ref=f"beat_{idx + 1:02d}_{beat_role}",
                    estimated_speech_duration_sec=est_dur,
                    visual_cue=f"Visuals corresponding to: {text[:40]}...",
                    fact_refs=[],
                )
            )

        full_script = " ".join(s.narration for s in scenes)
        title = default_title or f"Kịch bản: {scenes[0].narration[:30]}..."

        return ScriptPlan(
            title=title,
            full_script=full_script,
            scenes=scenes,
            total_word_count=len(re.findall(r"\w+", full_script)),
            estimated_total_duration_sec=round(len(re.findall(r"\w+", full_script)) / target_wps, 2),
            hook_word_count=len(re.findall(r"\w+", scenes[0].narration)) if scenes else 0,
        )


# ---------------------------------------------------------------------------
# JSON Security & Normalizer
# ---------------------------------------------------------------------------

class JSONNormalizer:
    """
    Validates developer-supplied JSON payloads with strict security assertions:
    - Payload size <= 1MB
    - No path traversal (../, ..\\)
    - No internal system paths (/etc/, C:\\Windows, /sys/, /proc/)
    - No internal file schemes (file://)
    - No internal storage key leakage
    """
    @classmethod
    def validate_security(cls, payload: Any) -> None:
        # 1. Size constraint
        serialized = json.dumps(payload, default=str)
        if len(serialized.encode("utf-8")) > MAX_JSON_PAYLOAD_BYTES:
            raise ValueError(f"Payload exceeds maximum allowed size of {MAX_JSON_PAYLOAD_BYTES} bytes.")

        # 2. Deep scan all string leaves
        def _scan(item: Any) -> None:
            if isinstance(item, str):
                s_lower = item.lower().strip()
                # Path traversal
                if "../" in s_lower or "..\\" in s_lower:
                    raise ValueError(f"Security Violation: Path traversal detected in input: '{item}'")
                # Forbidden system root paths
                if re.search(r"^[a-zA-Z]:[/\\]windows", s_lower) or s_lower.startswith("/etc/") or s_lower.startswith("/proc/") or s_lower.startswith("/sys/"):
                    raise ValueError(f"Security Violation: Access to internal system paths is forbidden: '{item}'")
                # Forbidden file scheme
                if s_lower.startswith("file://") or s_lower.startswith("file:\\\\"):
                    raise ValueError(f"Security Violation: file:// URI scheme is forbidden: '{item}'")
                # Forbidden internal secret references
                if any(sec in s_lower for sec in ["internal_storage_key", "aws_secret_access_key", "gemini_api_key"]):
                    raise ValueError(f"Security Violation: Internal credentials or storage keys cannot be referenced.")
            elif isinstance(item, dict):
                for k, v in item.items():
                    _scan(k)
                    _scan(v)
            elif isinstance(item, list):
                for elem in item:
                    _scan(elem)

        _scan(payload)

    @classmethod
    def normalize_payload(cls, payload: Dict[str, Any]) -> Dict[str, Any]:
        cls.validate_security(payload)

        # If payload represents ScriptPlan, validate schema
        if "scenes" in payload and "full_script" in payload:
            ScriptPlan.model_validate(payload)
        elif "scenes" in payload and "plan_id" in payload:
            EditorPlan.model_validate(payload)

        return payload


# ---------------------------------------------------------------------------
# Input Normalizer
# ---------------------------------------------------------------------------

class InputNormalizer:
    @staticmethod
    def infer_format_from_text(text: str) -> ProductionFormat:
        lower = text.lower()
        if any(term in lower for term in ["short", "shorts", "tiktok", "reels", "60s", "dọc", "9:16", "nhanh"]):
            return ProductionFormat.SHORT
        if any(term in lower for term in ["dài", "long", "chi tiết", "16:9", "ngang", "tài liệu", "full"]):
            return ProductionFormat.LONG
        return ProductionFormat.SHORT  # Default north-star format is short

    @staticmethod
    def detect_source_kind(uri_or_path: str) -> SourceKind:
        lower = uri_or_path.lower()
        if lower.startswith("http://") or lower.startswith("https://"):
            if any(domain in lower for domain in ["douyin.com", "tiktok.com", "youtube.com", "youtu.be"]):
                return SourceKind.URL
            return SourceKind.ARTICLE
        if any(lower.endswith(ext) for ext in [".mp4", ".mov", ".mkv", ".webm", ".avi"]):
            return SourceKind.VIDEO
        if any(lower.endswith(ext) for ext in [".mp3", ".wav", ".m4a", ".aac", ".flac"]):
            return SourceKind.AUDIO
        if any(lower.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"]):
            return SourceKind.IMAGE
        if any(lower.endswith(ext) for ext in [".pdf", ".docx", ".txt", ".md"]):
            return SourceKind.DOCUMENT
        return SourceKind.URL

    @classmethod
    def normalize(
        cls,
        raw_instruction: Optional[str] = None,
        raw_sources: Optional[List[Dict[str, Any]]] = None,
        requested_format: str = "auto",
        language: str = "vi",
        channel_profile_id: Optional[str] = None,
        target_duration_sec: Optional[float] = None,
        review_mode: str = "final_only",
        overrides: Optional[Dict[str, Any]] = None,
        input_mode: Any = InputMode.AUTO,
        raw_script: Optional[str] = None,
        structured_payload: Optional[Dict[str, Any]] = None,
        run_environment: Any = RunEnvironment.DEV,
    ) -> AutoVideoRequest:
        # Normalize input mode
        if isinstance(input_mode, str):
            mode_enum = InputMode(input_mode.upper())
        elif isinstance(input_mode, InputMode):
            mode_enum = input_mode
        else:
            mode_enum = InputMode.AUTO

        # Normalize run environment
        if isinstance(run_environment, str):
            env_enum = RunEnvironment(run_environment.upper())
        elif isinstance(run_environment, RunEnvironment):
            env_enum = run_environment
        else:
            env_enum = RunEnvironment.DEV

        instruction = (raw_instruction or "").strip()
        cleaned_raw_script = raw_script.strip() if raw_script else None
        cleaned_structured_payload = structured_payload

        # Mode-specific normalization
        if mode_enum == InputMode.SCRIPT:
            if not cleaned_raw_script and instruction:
                # If user passed script in instruction field under SCRIPT mode
                cleaned_raw_script = instruction
            if not cleaned_raw_script:
                raise ValueError("SCRIPT mode requires non-empty raw_script.")
            if not instruction:
                instruction = cleaned_raw_script[:100] + "..."

        elif mode_enum == InputMode.JSON:
            if not cleaned_structured_payload:
                raise ValueError("JSON mode requires structured_payload dictionary.")
            JSONNormalizer.normalize_payload(cleaned_structured_payload)
            if not instruction:
                instruction = cleaned_structured_payload.get("title", "Developer JSON Request")

        sources: List[SourceInput] = []

        # Extract URLs if embedded inside instruction text
        if instruction:
            urls = re.findall(r"https?://[^\s]+", instruction)
            for url in urls:
                source_id = f"src_{uuid.uuid4().hex[:8]}"
                sources.append(
                    SourceInput(
                        source_id=source_id,
                        kind=cls.detect_source_kind(url),
                        uri=url,
                        rights_state=RightsState.UNKNOWN,
                    )
                )

        # Parse explicitly provided sources
        if raw_sources:
            for s in raw_sources:
                sid = s.get("source_id") or f"src_{uuid.uuid4().hex[:8]}"
                uri = s.get("uri")
                file_ref = s.get("file_ref")
                kind_val = s.get("kind")
                if not kind_val and (uri or file_ref):
                    kind = cls.detect_source_kind(uri or file_ref or "")
                else:
                    kind = SourceKind(kind_val) if kind_val else SourceKind.URL

                rights_val = s.get("rights_state", RightsState.UNKNOWN.value)
                sources.append(
                    SourceInput(
                        source_id=sid,
                        kind=kind,
                        uri=uri,
                        file_ref=file_ref,
                        rights_state=RightsState(rights_val),
                        provenance=str(s.get("provenance", "USER")).upper(),
                    )
                )

        # Resolve format
        if requested_format == "auto":
            format_enum = cls.infer_format_from_text(instruction)
        else:
            format_enum = ProductionFormat(requested_format)

        # Fallback target duration from config if not explicitly set
        if not target_duration_sec:
            format_conf = config_loader.get_format_defaults(format_enum.value)
            target_duration_sec = float(format_conf.get("target_duration_sec", 55.0))

        return AutoVideoRequest(
            request_id=f"req_{uuid.uuid4().hex[:12]}",
            input_mode=mode_enum,
            instruction=instruction,
            raw_script=cleaned_raw_script,
            structured_payload=cleaned_structured_payload,
            format=format_enum,
            language=language,
            channel_profile_id=channel_profile_id,
            target_duration_sec=target_duration_sec,
            review_mode=ReviewMode(review_mode),
            run_environment=env_enum,
            sources=sources,
            overrides=overrides or {},
        )
