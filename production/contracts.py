"""
Pydantic Contracts & Schemas for VisionFlow Auto Production System (v1)
Single Source of Truth for Auto Production Request, Stages, EditorPlan, SceneAsset, and QualityReport.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


class ProductionFormat(str, Enum):
    AUTO = "auto"
    SHORT = "short"
    LONG = "long"


class RunEnvironment(str, Enum):
    FIXTURE = "FIXTURE"
    DEV = "DEV"
    PILOT = "PILOT"
    PRODUCTION = "PRODUCTION"


class ManualInterventionType(str, Enum):
    SCRIPT_EDITED = "script_edited"
    HOOK_EDITED = "hook_edited"
    VISUAL_CHANGED = "visual_changed"
    ASSET_LOCKED = "asset_locked"
    VOICE_REGENERATED = "voice_regenerated"
    SUBTITLE_ADJUSTED = "subtitle_adjusted"
    FACT_CORRECTED = "fact_corrected"
    SOURCE_CHANGED = "source_changed"


class ReviewSource(str, Enum):
    REAL_OPERATOR = "REAL_OPERATOR"
    SIMULATED_OPERATOR = "SIMULATED_OPERATOR"
    TEST_FIXTURE = "TEST_FIXTURE"


class InterventionSource(str, Enum):
    REAL_OPERATOR = "REAL_OPERATOR"
    AUTO_FIX = "AUTO_FIX"
    SIMULATED_OPERATOR = "SIMULATED_OPERATOR"
    TEST_FIXTURE = "TEST_FIXTURE"


class ProviderMode(str, Enum):
    MOCK = "MOCK"
    SIMULATION = "SIMULATION"
    LIVE = "LIVE"


class SceneFeedbackTag(str, Enum):
    GOOD = "GOOD"
    ACCEPTABLE = "ACCEPTABLE"
    WRONG_VISUAL = "WRONG_VISUAL"
    WEAK_VISUAL = "WEAK_VISUAL"
    REPETITIVE = "REPETITIVE"
    BAD_CROP = "BAD_CROP"
    FACT_PROBLEM = "FACT_PROBLEM"
    PACING_PROBLEM = "PACING_PROBLEM"


class ChannelRecommendationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ReviewMode(str, Enum):
    FINAL_ONLY = "final_only"
    BEFORE_RENDER = "before_render"
    MANUAL = "manual"


class SourceKind(str, Enum):
    URL = "url"
    VIDEO = "video"
    AUDIO = "audio"
    IMAGE = "image"
    ARTICLE = "article"
    DOCUMENT = "document"
    FOLDER = "folder"


class RightsState(str, Enum):
    OWNED = "OWNED"
    LICENSED_COMMERCIAL = "LICENSED_COMMERCIAL"
    PERMISSION_COMMERCIAL = "PERMISSION_COMMERCIAL"
    APPROVED_STOCK = "APPROVED_STOCK"
    UNKNOWN = "UNKNOWN"
    RESTRICTED = "RESTRICTED"
    BLOCKED = "BLOCKED"


class WatermarkState(str, Enum):
    NONE = "none"
    POSSIBLE = "possible"
    VISIBLE = "visible"


class SourceIngestState(str, Enum):
    ACCEPTED_AS_INPUT = "ACCEPTED_AS_INPUT"
    INGESTING = "INGESTING"
    INGESTED = "INGESTED"
    INDEXING = "INDEXING"
    ANALYZING = "ANALYZING"
    READY = "READY"
    FAILED = "FAILED"



class ProductionRunStatus(str, Enum):
    CREATED = "CREATED"
    INPUT_NORMALIZED = "INPUT_NORMALIZED"
    SOURCES_READY = "SOURCES_READY"
    SOURCE_INDEXED = "SOURCE_INDEXED"
    RESEARCH_READY = "RESEARCH_READY"
    STORY_READY = "STORY_READY"
    SCRIPT_READY = "SCRIPT_READY"
    SCRIPT_VALIDATED = "SCRIPT_VALIDATED"
    VISUAL_PLAN_READY = "VISUAL_PLAN_READY"
    ASSETS_RESOLVED = "ASSETS_RESOLVED"
    EDITOR_PLAN_READY = "EDITOR_PLAN_READY"
    AUDIO_READY = "AUDIO_READY"
    TIMELINE_READY = "TIMELINE_READY"
    WAITING_FOR_RENDER_WORKER = "WAITING_FOR_RENDER_WORKER"
    DOWNLOADING_RENDER_ASSETS = "DOWNLOADING_RENDER_ASSETS"
    UPLOADING_RENDER = "UPLOADING_RENDER"
    RENDERING = "RENDERING"
    RENDERED = "RENDERED"
    QC_RUNNING = "QC_RUNNING"
    QC_PASSED = "QC_PASSED"
    FOUNDATION_READY = "FOUNDATION_READY"
    DRAFT_PIPELINE_READY = "DRAFT_PIPELINE_READY"
    READY = "READY"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    BLOCKED_RIGHTS = "BLOCKED_RIGHTS"
    BLOCKED_FACTS = "BLOCKED_FACTS"
    RENDER_FAILED = "RENDER_FAILED"
    QC_RETRY = "QC_RETRY"
    QC_FAILED = "QC_FAILED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    HUMAN_REVIEW_PENDING = "HUMAN_REVIEW_PENDING"
    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"


class StageStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class PublicationStatus(str, Enum):
    NOT_APPROVED = "NOT_APPROVED"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    SIMULATED_PUBLISHED = "SIMULATED_PUBLISHED"
    PUBLISH_FAILED = "PUBLISH_FAILED"


class RenderJobState(str, Enum):
    QUEUED = "QUEUED"
    WAITING_FOR_WORKER = "WAITING_FOR_WORKER"
    CLAIMED = "CLAIMED"
    DOWNLOADING = "DOWNLOADING"
    RENDERING = "RENDERING"
    UPLOADING = "UPLOADING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"


class StorageTier(str, Enum):
    RAW = "RAW"
    DERIVED = "DERIVED"
    TEMP = "TEMP"
    FINAL = "FINAL"


# ---------------------------------------------------------------------------
# Input Schemas
# ---------------------------------------------------------------------------

class SourceInput(BaseModel):
    source_id: str = Field(description="Unique ID for this source")
    kind: SourceKind = Field(default=SourceKind.URL)
    uri: Optional[str] = None
    file_ref: Optional[str] = None
    rights_state: RightsState = Field(default=RightsState.UNKNOWN)
    ingest_state: SourceIngestState = Field(default=SourceIngestState.ACCEPTED_AS_INPUT)
    provenance: str = "USER"  # USER, FIXTURE, STOCK, SCENE_LIBRARY


class InputMode(str, Enum):
    AUTO = "AUTO"
    SCRIPT = "SCRIPT"
    JSON = "JSON"


class AutoVideoRequest(BaseModel):
    request_id: str = Field(description="Unique client request ID")
    input_mode: InputMode = Field(default=InputMode.AUTO, description="Execution input mode: AUTO, SCRIPT, or JSON")
    instruction: Optional[str] = Field(default=None, description="Topic or natural language instruction")
    raw_script: Optional[str] = Field(default=None, description="Direct plain text script for SCRIPT mode")
    structured_payload: Optional[Dict[str, Any]] = Field(default=None, description="Pre-formed JSON payload for JSON mode")
    format: ProductionFormat = Field(default=ProductionFormat.AUTO)
    language: str = Field(default="vi")
    channel_profile_id: Optional[str] = None
    target_duration_sec: Optional[float] = Field(default=None, ge=5.0)
    review_mode: ReviewMode = Field(default=ReviewMode.FINAL_ONLY)
    run_environment: RunEnvironment = Field(default=RunEnvironment.DEV, description="FIXTURE, DEV, PILOT, or PRODUCTION")
    sources: List[SourceInput] = Field(default_factory=list)
    overrides: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_instruction_or_sources(self) -> AutoVideoRequest:
        if not self.instruction and not self.sources and not self.raw_script and not self.structured_payload:
            raise ValueError("Either instruction, at least one source, raw_script, or structured_payload must be provided.")
        return self


# ---------------------------------------------------------------------------
# Visual & Scene Intelligence Schemas
# ---------------------------------------------------------------------------

class VisualRole(str, Enum):
    HOOK = "HOOK"
    ESTABLISHING = "ESTABLISHING"
    PROCESS = "PROCESS"
    DETAIL = "DETAIL"
    EVIDENCE = "EVIDENCE"
    CONTRAST = "CONTRAST"
    REVEAL = "REVEAL"
    RESET = "RESET"
    GRAPHIC = "GRAPHIC"
    TRANSITION_SUPPORT = "TRANSITION_SUPPORT"


class VisualIntent(BaseModel):
    """
    Canonical specification of what the audience needs to see for a narration beat/shot.
    Independent of physical media file or URL selection.
    """
    id: str = Field(default="", description="e.g. vi_001")
    scene_id: str = Field(default="", description="e.g. scene_001")
    shot_order: int = Field(default=1, ge=1, description="Order within the parent scene (1-based)")
    visual_role: str = Field(default="PROCESS", description="VisualRole enum value")
    description: str = Field(default="", description="Detailed visual description of footage required")
    search_query_en: str = Field(default="", description="Canonical English retrieval query")
    subjects: List[str] = Field(default_factory=list, description="Primary visual entities/objects required")
    actions: List[str] = Field(default_factory=list, description="Physical actions or processes occurring")
    setting: Optional[str] = Field(default=None, description="Physical environment or setting")
    shot_preferences: List[str] = Field(default_factory=lambda: ["medium_close_up"])
    motion_preference: str = Field(default="active", description="active, subtle, static, dynamic")
    must_show: List[str] = Field(default_factory=list)
    must_avoid: List[str] = Field(default_factory=list)
    fact_refs: List[str] = Field(default_factory=list, description="Linked ClaimItem fact IDs")
    importance: float = Field(default=0.9, ge=0.0, le=1.0)
    duration_weight: float = Field(default=1.0, ge=0.1)

    @property
    def semantic_query(self) -> str:
        return self.search_query_en or self.description

    @property
    def action_verbs(self) -> List[str]:
        return self.actions

    @model_validator(mode="after")
    def ensure_id(self) -> VisualIntent:
        if not self.id:
            import uuid
            self.id = f"vi_{uuid.uuid4().hex[:6]}"
        return self


class VisualPlan(BaseModel):
    """
    Comprehensive visual architecture for a video project containing structured VisualIntents.
    """
    plan_id: str = Field(default="", description="e.g. vp_001")
    run_id: Optional[str] = None
    title: Optional[str] = None
    intents: List[VisualIntent] = Field(default_factory=list)
    total_shots: int = 0
    planner_mode: str = Field(default="LOCAL_DOMAIN_RULES", description="CLOUD_SEMANTIC, LOCAL_DOMAIN_RULES, or GENERIC_FALLBACK")
    warnings: List[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None

    @model_validator(mode="after")
    def compute_stats(self) -> VisualPlan:
        if not self.plan_id:
            import uuid
            self.plan_id = f"vp_{uuid.uuid4().hex[:8]}"
        self.total_shots = len(self.intents)
        return self

    def get_intents_for_scene(self, scene_id: str) -> List[VisualIntent]:
        return [vi for vi in self.intents if vi.scene_id == scene_id]


class AssetCandidate(BaseModel):
    """
    Candidate footage item resolved from a real provider for a specific VisualIntent.
    """
    asset_id: str
    source_id: str
    provider: str = Field(description="user_source, scene_library, pexels_stock, graphic_fallback")
    start_sec: float = Field(default=0.0, ge=0.0)
    end_sec: float = Field(default=0.0, ge=0.0)
    duration_sec: float = Field(default=0.0, ge=0.0)
    thumbnail_url: Optional[str] = None
    media_url: Optional[str] = None
    semantic_score: float = Field(default=0.0, ge=0.0, le=1.0)
    entity_action_score: float = Field(default=0.0, ge=0.0, le=1.0)
    visual_role_score: float = Field(default=0.0, ge=0.0, le=1.0)
    shot_type_score: float = Field(default=0.0, ge=0.0, le=1.0)
    technical_quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    duration_fit_score: float = Field(default=0.0, ge=0.0, le=1.0)
    source_diversity_score: float = Field(default=0.0, ge=0.0, le=1.0)
    rights_score: float = Field(default=1.0, ge=0.0, le=1.0)
    repetition_penalty: float = Field(default=0.0, ge=0.0)
    watermark_penalty: float = Field(default=0.0, ge=0.0)
    conflict_penalty: float = Field(default=0.0, ge=0.0)
    composite_score: float = Field(default=0.0, ge=0.0, le=1.0)
    visual_fingerprint: Optional[str] = None
    rights_state: RightsState = RightsState.OWNED
    is_locked: bool = False
    provenance: Dict[str, Any] = Field(default_factory=dict)
    selection_evidence: Dict[str, Any] = Field(default_factory=dict)


class SceneAssetResolution(BaseModel):
    scene_id: str
    shot_order: int = 1
    intent_id: str
    selected_candidate: Optional[AssetCandidate] = None
    alternate_candidates: List[AssetCandidate] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    rejection_reasons: List[str] = Field(default_factory=list)
    is_unresolved: bool = False


class AssetResolutionResult(BaseModel):
    run_id: str
    resolutions: List[SceneAssetResolution] = Field(default_factory=list)
    visual_coverage_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    duplicate_count: int = 0
    rights_blocker_count: int = 0
    unresolved_count: int = 0
    average_match_score: float = 0.0
    cache_hit: bool = False
    resolved_at: Optional[datetime] = None

    @property
    def selected_assets(self) -> List[AssetCandidate]:
        return [r.selected_candidate for r in self.resolutions if r.selected_candidate is not None]


class SceneAsset(BaseModel):
    scene_id: str
    source_id: str
    start_sec: float = Field(ge=0.0)
    end_sec: float = Field(gt=0.0)
    description: str
    transcript: Optional[str] = None
    entities: List[str] = Field(default_factory=list)
    actions: List[str] = Field(default_factory=list)
    shot_type: Optional[str] = None
    motion_score: float = Field(default=0.5, ge=0.0, le=1.0)
    technical_quality_score: float = Field(default=0.8, ge=0.0, le=1.0)
    watermark_state: WatermarkState = Field(default=WatermarkState.NONE)
    rights_state: RightsState = Field(default=RightsState.UNKNOWN)
    fingerprint: str = ""
    embedding_ref: Optional[str] = None


class RetrievalMode(str, Enum):
    CLOUD_SEMANTIC = "CLOUD_SEMANTIC"
    LOCAL_SEMANTIC = "LOCAL_SEMANTIC"
    LEXICAL_FALLBACK = "LEXICAL_FALLBACK"


class SourceAssetRecord(BaseModel):
    id: str
    source_type: str = "video"
    original_uri: Optional[str] = None
    storage_ref: Optional[str] = None
    fingerprint: str
    fast_fingerprint: Optional[str] = None
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    codec: str = "unknown"
    language: Optional[str] = None
    transcript_state: str = "PENDING"
    rights_state: RightsState = RightsState.UNKNOWN
    watermark_state: WatermarkState = WatermarkState.NONE
    ingest_status: SourceIngestState = SourceIngestState.INGESTED
    analysis_version: str = "v1"
    metadata_json: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None

    @property
    def fingerprint_short(self) -> str:
        if self.fingerprint and len(self.fingerprint) > 16:
            return f"{self.fingerprint[:11]}...{self.fingerprint[-4:]}"
        return self.fingerprint


class SourceSceneRecord(BaseModel):
    id: str
    source_id: str
    start_sec: float
    end_sec: float
    duration_sec: float
    fingerprint: str
    visual_fingerprint: Optional[str] = None
    description: str = ""
    transcript: Optional[str] = None
    entities: List[Dict[str, Any]] = Field(default_factory=list)
    actions: List[Dict[str, Any]] = Field(default_factory=list)
    location_context: Optional[str] = None
    shot_type: Optional[str] = None
    motion_score: float = 0.5
    technical_quality_score: float = 0.8
    embedding_ref: Optional[str] = None
    analysis_version: str = "v1"
    keyframes: List[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None


class EmbeddingRecord(BaseModel):
    id: str
    scene_id: str
    vector: List[float] = Field(default_factory=list)
    text_repr: str = ""
    provider: str = "local"
    model: str = "hashed-lexical-v1"
    dimensions: int = 256
    embedding_version: str = "v1"
    created_at: Optional[datetime] = None


class SceneSearchFilter(BaseModel):
    source_ids: Optional[List[str]] = None
    rights_states: Optional[List[RightsState]] = None
    min_technical_quality: float = 0.0
    duration_range: Optional[List[float]] = None
    shot_type: Optional[str] = None
    watermark_states: Optional[List[WatermarkState]] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    dimensions: Optional[int] = None
    embedding_version: Optional[str] = None


class SceneSearchResult(BaseModel):
    scene_id: str
    source_id: str
    score: float
    start_sec: float
    end_sec: float
    duration_sec: float
    description: str
    match_evidence: Dict[str, Any] = Field(default_factory=dict)
    scene: Optional[SourceSceneRecord] = None
    retrieval_mode: RetrievalMode = RetrievalMode.LEXICAL_FALLBACK
    latency_ms: float = 0.0
    possible_duplicate_group: Optional[str] = None



# ---------------------------------------------------------------------------
# Editor Plan Schemas
# ---------------------------------------------------------------------------

class EditorPlanType(str, Enum):
    DRAFT = "DRAFT_EDITOR_PLAN"
    FINAL = "FINAL_EDITOR_PLAN"


class SubtitleAlignmentMode(str, Enum):
    WORD_BOUNDARY = "WORD_BOUNDARY"
    ASR_ALIGNED = "ASR_ALIGNED"
    PROPORTIONAL_FALLBACK = "PROPORTIONAL_FALLBACK"


class ShortAssetFallbackPolicy(str, Enum):
    ALTERNATE_CANDIDATE = "ALTERNATE_CANDIDATE"
    REDISTRIBUTE_DURATION = "REDISTRIBUTE_DURATION"
    PERMITTED_LOOP = "PERMITTED_LOOP"
    DERIVED_STILL = "DERIVED_STILL"
    KEN_BURNS_ON_STILL = "KEN_BURNS_ON_STILL"
    GRAPHIC_FALLBACK = "GRAPHIC_FALLBACK"


class SubtitleChunkPlan(BaseModel):
    chunk_id: Optional[str] = None
    text: str
    start_sec: float = Field(default=0.0, ge=0.0)
    end_sec: float = Field(default=0.0, ge=0.0)
    duration_sec: float = Field(default=0.0, ge=0.0)
    timeline_start: Optional[float] = None
    timeline_end: Optional[float] = None
    duration_seconds: Optional[float] = None
    scene_id: Optional[str] = None
    alignment_mode: SubtitleAlignmentMode = Field(default=SubtitleAlignmentMode.PROPORTIONAL_FALLBACK)

    @model_validator(mode="after")
    def sync_subtitle_timing(self) -> SubtitleChunkPlan:
        if self.timeline_start is None:
            self.timeline_start = self.start_sec
        elif self.start_sec == 0.0 and self.timeline_start > 0.0:
            self.start_sec = self.timeline_start

        if self.timeline_end is None:
            self.timeline_end = self.end_sec
        elif self.end_sec == 0.0 and self.timeline_end > 0.0:
            self.end_sec = self.timeline_end

        if self.duration_seconds is None:
            self.duration_seconds = self.duration_sec
        elif self.duration_sec == 0.0 and self.duration_seconds > 0.0:
            self.duration_sec = self.duration_seconds

        if not self.chunk_id:
            import uuid
            self.chunk_id = f"chk_{uuid.uuid4().hex[:6]}"
        return self


class SubtitleTrackPlan(BaseModel):
    track_id: str = "track_subtitles"
    language: str = "vi"
    chunks: List[SubtitleChunkPlan] = Field(default_factory=list)
    safe_margin_px: Dict[str, int] = Field(default_factory=lambda: {"top": 120, "bottom": 240, "left": 40, "right": 40})

    @property
    def alignment_mode(self) -> SubtitleAlignmentMode:
        if self.chunks:
            return getattr(self.chunks[0], "alignment_mode", SubtitleAlignmentMode.WORD_BOUNDARY)
        return SubtitleAlignmentMode.WORD_BOUNDARY


class AudioClipPlan(BaseModel):
    clip_id: str
    type: str = "voice"
    scene_id: Optional[str] = None
    audio_asset_id: str = ""
    file_path: Optional[str] = None
    source_file_path: Optional[str] = None
    timeline_start: float = Field(default=0.0, ge=0.0)
    timeline_end: float = Field(default=0.0, ge=0.0)
    duration_sec: float = Field(default=0.0, ge=0.0)
    duration_seconds: Optional[float] = None
    volume: float = 1.0
    volume_db: Optional[float] = None
    fade_in_sec: float = 0.0
    fade_out_sec: float = 0.0
    ducking_factor: Optional[float] = None

    @model_validator(mode="after")
    def sync_audio_fields(self) -> AudioClipPlan:
        if self.source_file_path and not self.file_path:
            self.file_path = self.source_file_path
        elif self.file_path and not self.source_file_path:
            self.source_file_path = self.file_path

        if self.duration_seconds is None:
            self.duration_seconds = self.duration_sec
        elif self.duration_sec == 0.0 and self.duration_seconds > 0.0:
            self.duration_sec = self.duration_seconds

        if self.volume_db is None and self.volume > 0.0:
            import math
            self.volume_db = round(20.0 * math.log10(self.volume), 2)
        elif self.volume_db is not None and self.volume == 1.0 and self.volume_db != 0.0:
            self.volume = round(10.0 ** (self.volume_db / 20.0), 3)
        return self


class AudioTrackPlan(BaseModel):
    voice_clips: List[AudioClipPlan] = Field(default_factory=list)
    clips: List[AudioClipPlan] = Field(default_factory=list)
    music_clip: Optional[AudioClipPlan] = None
    ducking_enabled: bool = True
    ducking_idle_db: float = -18.0
    ducking_speech_db: float = -30.0

    @model_validator(mode="after")
    def sync_clips(self) -> AudioTrackPlan:
        if self.voice_clips and not self.clips:
            self.clips = list(self.voice_clips)
            if self.music_clip:
                self.clips.append(self.music_clip)
        elif self.clips and not self.voice_clips:
            self.voice_clips = [c for c in self.clips if c.type == "voice"]
            self.music_clip = next((c for c in self.clips if c.type in ("bgm", "music")), None)
        return self


class ShotPlan(BaseModel):
    shot_id: str
    shot_index: Optional[int] = None
    asset_id: str
    source_id: Optional[str] = None
    provider: Optional[str] = None
    media_url: Optional[str] = None
    asset_file_path: Optional[str] = None
    thumbnail_url: Optional[str] = None
    timeline_start: float = Field(default=0.0, ge=0.0)
    timeline_end: float = Field(default=0.0, ge=0.0)
    duration_sec: float = Field(default=0.0, ge=0.0)
    target_duration_seconds: Optional[float] = None
    duration_seconds: Optional[float] = None
    asset_trim_start: float = Field(default=0.0, ge=0.0)
    asset_trim_end: float = Field(default=0.0, ge=0.0)
    asset_start_sec: float = Field(default=0.0, ge=0.0)  # legacy alias
    asset_end_sec: float = Field(default=0.0, ge=0.0)    # legacy alias
    visual_role: str = "PROCESS"
    visual_prompt: Optional[str] = None
    keyword: Optional[str] = None
    caption: Optional[str] = None
    transition_in: Optional[str] = None
    transition_out: Optional[str] = "cut"
    transition: Optional[str] = None                     # legacy alias
    transition_duration_sec: float = 0.0
    motion_effect: Optional[str] = None                  # e.g. ken_burns_zoom_in, static_hold
    match_score: float = Field(default=1.0, ge=0.0, le=1.0)
    is_locked: bool = False
    is_graphic_fallback: bool = False
    fallback_policy: Optional[ShortAssetFallbackPolicy] = None
    provenance: Dict[str, Any] = Field(default_factory=dict)
    provenance_ref: Optional[str] = None
    resolved_asset: Optional[AssetCandidate] = None

    @model_validator(mode="after")
    def sync_trim_fields(self) -> ShotPlan:
        # Sync target_duration_seconds / duration_sec / duration_seconds
        dur = self.duration_sec or self.target_duration_seconds or self.duration_seconds or 0.0
        if self.duration_sec == 0.0 and dur > 0.0:
            self.duration_sec = dur
        if self.target_duration_seconds is None and dur > 0.0:
            self.target_duration_seconds = dur
        if self.duration_seconds is None and dur > 0.0:
            self.duration_seconds = dur

        # Sync asset_trim_start / asset_start_sec
        if self.asset_trim_start > 0 and self.asset_start_sec == 0:
            self.asset_start_sec = self.asset_trim_start
        elif self.asset_start_sec > 0 and self.asset_trim_start == 0:
            self.asset_trim_start = self.asset_start_sec

        # Sync asset_trim_end / asset_end_sec
        if self.asset_trim_end > 0 and self.asset_end_sec == 0:
            self.asset_end_sec = self.asset_trim_end
        elif self.asset_end_sec > 0 and self.asset_trim_end == 0:
            self.asset_trim_end = self.asset_end_sec

        # Sync transition
        if self.transition and not self.transition_out:
            self.transition_out = self.transition
        elif self.transition_out and not self.transition:
            self.transition = self.transition_out

        return self


class ScenePlan(BaseModel):
    """
    ScenePlan links canonical narration to resolved visual shots and actual voice audio.
    narration = CANONICAL CONTENT SOURCE
    actual_duration_seconds = CANONICAL TIMING SOURCE (populated strictly after TTS generation via ffprobe)
    """
    scene_id: str
    scene_index: Optional[int] = None
    narration: str
    audio_asset_id: Optional[str] = None
    audio_file_path: Optional[str] = None
    actual_duration_seconds: Optional[float] = None
    actual_duration_sec: Optional[float] = None          # legacy alias
    target_duration_seconds: Optional[float] = None
    timeline_start: float = Field(default=0.0, ge=0.0)
    timeline_end: float = Field(default=0.0, ge=0.0)
    shots: List[ShotPlan] = Field(default_factory=list)

    @model_validator(mode="after")
    def sync_duration_fields(self) -> ScenePlan:
        if self.actual_duration_seconds is not None and self.actual_duration_sec is None:
            self.actual_duration_sec = self.actual_duration_seconds
        elif self.actual_duration_sec is not None and self.actual_duration_seconds is None:
            self.actual_duration_seconds = self.actual_duration_sec

        # Derive scene_index from scene_id if not explicitly set (e.g. scene_001 -> 1)
        if self.scene_index is None and self.scene_id:
            import re
            m = re.search(r'\d+', self.scene_id)
            if m:
                self.scene_index = int(m.group(0))

        return self


class EditorPlan(BaseModel):
    plan_id: str
    run_id: Optional[str] = None
    script_version: Optional[str] = "1.0"
    plan_type: str = EditorPlanType.DRAFT.value
    duration_seconds: float = 0.0
    total_duration_sec: Optional[float] = None
    total_duration_seconds: Optional[float] = None
    aspect_ratio: str = "9:16"
    timeline_drift_ms: float = 0.0
    scenes: List[ScenePlan] = Field(default_factory=list)
    audio_track: Optional[AudioTrackPlan] = None
    subtitle_track: Optional[SubtitleTrackPlan] = None
    is_render_ready: bool = False
    created_at: Optional[datetime] = None

    @model_validator(mode="after")
    def compute_total_duration(self) -> EditorPlan:
        if self.scenes:
            last_end = max((s.timeline_end for s in self.scenes), default=0.0)
            if self.duration_seconds == 0.0:
                self.duration_seconds = round(last_end, 3)
        if self.total_duration_sec is None:
            self.total_duration_sec = self.duration_seconds
        if self.total_duration_seconds is None:
            self.total_duration_seconds = self.duration_seconds
        return self


# ---------------------------------------------------------------------------
# Quality System Schemas
# ---------------------------------------------------------------------------

class QualityStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    NOT_EVALUATED = "NOT_EVALUATED"
    PENDING = "PENDING"


class QualityAxisReport(BaseModel):
    status: QualityStatus = QualityStatus.NOT_EVALUATED
    score: Optional[float] = None
    evidence: List[str] = Field(default_factory=list)
    blockers: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class RenderArtifact(BaseModel):
    storage_ref: Optional[str] = None
    checksum_sha256: Optional[str] = None
    run_id: str
    output_path_ref: str
    duration_seconds: float
    width: int = 1080
    height: int = 1920
    fps: int = 30
    video_codec: str = "h264"
    audio_codec: str = "aac"
    file_size_bytes: int = 0
    rendered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    internal_file_path: Optional[str] = Field(default=None, exclude=True)  # Protected from public API responses

    @property
    def actual_duration_seconds(self) -> float:
        return self.duration_seconds

    @property
    def resolution_width(self) -> int:
        return self.width

    @property
    def resolution_height(self) -> int:
        return self.height


class QualityReport(BaseModel):
    report_id: str
    run_id: str
    stage_name: str
    overall_status: QualityStatus = QualityStatus.NOT_EVALUATED
    score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    blocker_count: int = 0
    warning_count: int = 0
    content_score: Optional[float] = None
    story_score: Optional[float] = None
    visual_score: Optional[float] = None
    edit_score: Optional[float] = None
    timeline_conformance_score: Optional[float] = None
    technical_score: Optional[float] = None
    rights_score: Optional[float] = None
    evaluated_axes: List[str] = Field(default_factory=list)
    axes: Dict[str, QualityAxisReport] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    blockers: List[str] = Field(default_factory=list)
    evaluator_disclaimer: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)



# ---------------------------------------------------------------------------
# Phase 3 Story & Script Engine Schemas
# ---------------------------------------------------------------------------

class EvidenceItem(BaseModel):
    """
    Represents an atomic piece of source or web evidence backing a claim.
    """
    id: str = Field(default="", description="Stable evidence ID, e.g. ev_001")
    claim_id: Optional[str] = Field(default=None, description="Linked claim ID if direct 1-1")
    snippet: str = Field(default="", description="Verbatim or summarized evidence snippet")
    source_kind: str = Field(default="USER_PROMPT", description="USER_PROMPT, SOURCE_DOCUMENT, WEB_SCRAPE, EXTERNAL_SEARCH")
    source_ref: Optional[str] = Field(default=None, description="URI or source identifier")
    retrieved_at: Optional[datetime] = None
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def ensure_id(self) -> EvidenceItem:
        if not self.id:
            import uuid
            self.id = f"ev_{uuid.uuid4().hex[:6]}"
        return self


class ClaimCriticality(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ClaimItem(BaseModel):
    """
    Atomic factual claim extracted during research with stable ID and evidence provenance.
    """
    id: str = Field(default="", description="Stable claim ID, e.g. fact_001")
    claim: str
    evidence: str
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    source_ref: Optional[str] = None
    criticality: str = Field(default="MEDIUM", description="HIGH, MEDIUM, or LOW")
    is_critical: bool = False
    evidence_refs: List[str] = Field(default_factory=list, description="IDs of supporting EvidenceItem, e.g. ['ev_001']")
    allowed_wording: Optional[str] = None

    @model_validator(mode="after")
    def ensure_id_and_criticality(self) -> ClaimItem:
        if not self.id:
            import uuid
            self.id = f"fact_{uuid.uuid4().hex[:6]}"
        if self.is_critical and self.criticality != "HIGH":
            self.criticality = "HIGH"
        elif self.criticality == "HIGH":
            self.is_critical = True
        return self


class FactPack(BaseModel):
    topic: str
    claims: List[ClaimItem] = Field(default_factory=list)
    confidence_score: float = Field(default=0.9, ge=0.0, le=1.0)
    entities: List[str] = Field(default_factory=list)
    suggested_angles: List[str] = Field(default_factory=list)
    contradictions: List[str] = Field(default_factory=list)
    # Provenance metadata
    research_mode: str = Field(default="SOURCE_EXTRACTION", description="SOURCE_EXTRACTION, WEB_SEARCH, DEEP_RESEARCH")
    provider: str = Field(default="local_input", description="local_input, gemini_web_grounded, perplexity, etc.")
    researched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_count: int = 0
    external_verification_performed: bool = False
    evidence_items: List[EvidenceItem] = Field(default_factory=list)


class NarrativeBeat(BaseModel):
    beat_id: str
    beat_type: str = "hook"  # hook, setup, twist, development, climax, payoff_cta
    summary: str = ""
    evidence_ref: Optional[str] = None
    visual_opportunity: str = ""
    estimated_duration_sec: float = Field(default=5.0, gt=0.0)


class StoryArchetype(str, Enum):
    PROCESS_EXPLAINER = "PROCESS_EXPLAINER"
    MYSTERY = "MYSTERY"
    TRANSFORMATION = "TRANSFORMATION"
    TIMELINE = "TIMELINE"
    CAUSE_EFFECT = "CAUSE_EFFECT"
    COMPARISON = "COMPARISON"
    INVESTIGATION = "INVESTIGATION"
    DISCOVERY = "DISCOVERY"


class StoryPlan(BaseModel):
    angle: str
    audience_promise: str
    hook_mechanism: str
    archetype: StoryArchetype = Field(default=StoryArchetype.PROCESS_EXPLAINER)
    beat_ratios: Dict[str, float] = Field(default_factory=dict, description="Beat duration allocation ratios")
    beats: List[NarrativeBeat] = Field(default_factory=list)
    excluded_interpretations: List[str] = Field(default_factory=list)
    target_duration_sec: float = Field(default=55.0, gt=0.0)
    tone: str = "curiosity"


class SceneNarration(BaseModel):
    """
    CANONICAL CONTENT SOURCE:
    scenes[].narration is the single source of truth for voiceover content,
    visual context, and semantic alignment.
    NOTE: Timing is estimated here (estimated_speech_duration_sec).
    The CANONICAL TIMING SOURCE is actual_duration_seconds, which is measured
    strictly downstream from TTS audio via ffprobe. Never populate actual_duration_seconds with estimates.
    """
    scene_id: Optional[str] = None
    scene_index: int = Field(ge=1)
    narration: str
    beat_ref: Optional[str] = None
    estimated_speech_duration_sec: float = Field(default=0.0, ge=0.0)
    visual_cue: Optional[str] = None
    fact_refs: List[str] = Field(default_factory=list, description="Claim IDs grounding this scene, e.g. ['fact_001']")


class ScriptPlan(BaseModel):
    title: str
    full_script: str
    scenes: List[SceneNarration] = Field(default_factory=list)
    total_word_count: int = 0
    estimated_total_duration_sec: float = 0.0
    hook_word_count: int = 0


class ScriptGateViolation(BaseModel):
    rule_id: str
    severity: str = "BLOCKER"  # BLOCKER or WARNING
    message: str
    scene_index: Optional[int] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class ScriptQualityGateReport(BaseModel):
    report_id: str
    run_id: Optional[str] = None
    status: QualityStatus = QualityStatus.PASS
    score: float = Field(default=1.0, ge=0.0, le=1.0)
    blocker_count: int = 0
    warning_count: int = 0
    violations: List[ScriptGateViolation] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)



# ---------------------------------------------------------------------------
# Lifecycle State Schemas
# ---------------------------------------------------------------------------

class ProductionStageRun(BaseModel):
    id: str
    run_id: str
    stage_name: str
    status: StageStatus = StageStatus.PENDING
    execution_mode: str = "STUB"  # REAL, STUB, CACHED
    is_cached: bool = False
    input_hash: Optional[str] = None
    output_version: Optional[str] = None
    model_name: Optional[str] = None
    duration_ms: Optional[int] = None
    cost_usd: float = 0.0
    error_code: Optional[str] = None
    output_json: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ProviderRoutingRecord(BaseModel):
    call_id: str = Field(default_factory=lambda: f"call_{int(datetime.now(timezone.utc).timestamp()*1000)}")
    stage: str
    provider: str
    model: str
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
    latency_ms: int = 0
    cost_usd: float = 0.0
    retry_count: int = 0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CostTelemetry(BaseModel):
    total_cost_usd: float = 0.0
    cost_per_video: float = 0.0
    cost_per_output_minute: float = 0.0
    llm_cost_usd: float = 0.0
    vlm_cost_usd: float = 0.0
    embedding_cost_usd: float = 0.0
    tts_cost_usd: float = 0.0
    stock_api_cost_usd: float = 0.0
    render_compute_seconds: float = 0.0
    llm_tokens_prompt: int = 0
    llm_tokens_completion: int = 0
    tts_characters: int = 0
    stock_assets_requested: int = 0
    records: List[ProviderRoutingRecord] = Field(default_factory=list)


class LatencyTelemetry(BaseModel):
    total_pipeline_duration_ms: int = 0
    stage_durations_ms: Dict[str, int] = Field(default_factory=dict)
    p50_stage_duration_ms: Optional[float] = None
    p95_stage_duration_ms: Optional[float] = None
    bottleneck_stage: Optional[str] = None


class HumanReviewRatings(BaseModel):
    hook_score: Optional[float] = Field(default=None, ge=1.0, le=5.0)
    script_score: Optional[float] = Field(default=None, ge=1.0, le=5.0)
    factual_confidence_score: Optional[float] = Field(default=None, ge=1.0, le=5.0)
    visual_relevance_score: Optional[float] = Field(default=None, ge=1.0, le=5.0)
    pacing_score: Optional[float] = Field(default=None, ge=1.0, le=5.0)
    subtitle_score: Optional[float] = Field(default=None, ge=1.0, le=5.0)
    audio_score: Optional[float] = Field(default=None, ge=1.0, le=5.0)
    overall_publishability: Optional[float] = Field(default=None, ge=1.0, le=5.0)


class SceneFeedbackItem(BaseModel):
    scene_index: int
    tag: SceneFeedbackTag
    notes: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ManualInterventionRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"intv_{uuid.uuid4().hex[:10]}")
    run_id: str
    intervention_type: ManualInterventionType
    scene_index: Optional[int] = None
    description: str = ""
    before_value: Optional[Any] = None
    after_value: Optional[Any] = None
    operator_id: str = "operator"
    intervention_source: InterventionSource = InterventionSource.REAL_OPERATOR
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class VisualReplacementGroundTruth(BaseModel):
    record_id: str = Field(default_factory=lambda: f"vgtruth_{uuid.uuid4().hex[:10]}")
    run_id: str
    scene_index: int
    rejected_asset_id: str
    rejected_asset_url: Optional[str] = None
    selected_replacement_id: str
    selected_replacement_url: Optional[str] = None
    visual_intent: Optional[Dict[str, Any]] = None
    reason: str = ""
    operator_id: str = "operator"
    intervention_source: InterventionSource = InterventionSource.REAL_OPERATOR
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ScriptDiffGroundTruth(BaseModel):
    diff_id: str = Field(default_factory=lambda: f"sgtruth_{uuid.uuid4().hex[:10]}")
    run_id: str
    original_title: str
    edited_title: str
    hook_changed: bool = False
    original_hook: str = ""
    edited_hook: str = ""
    words_delta: int = 0
    scene_diffs: List[Dict[str, Any]] = Field(default_factory=list)
    categories: List[str] = Field(default_factory=list)
    operator_id: str = "operator"
    intervention_source: InterventionSource = InterventionSource.REAL_OPERATOR
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ChannelProfileRecommendation(BaseModel):
    recommendation_id: str = Field(default_factory=lambda: f"rec_{uuid.uuid4().hex[:10]}")
    channel_id: str
    parameter: str  # e.g. voice_rate, hook_cut_pace, target_duration_seconds, stock_ratio, subtitle_preset
    current_value: Any
    suggested_value: Any
    confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    evidence: str = ""
    status: ChannelRecommendationStatus = ChannelRecommendationStatus.PENDING
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    approval_source: Optional[ReviewSource] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class HumanReviewRecord(BaseModel):
    review_id: str = Field(default_factory=lambda: f"rev_{int(datetime.now(timezone.utc).timestamp())}")
    run_id: str
    reviewer: str
    reviewer_id: Optional[str] = None
    review_source: ReviewSource = ReviewSource.REAL_OPERATOR
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    client_source: Optional[str] = None
    session_id: Optional[str] = None
    ratings: Optional[HumanReviewRatings] = None
    notes: Optional[str] = None
    changed_scenes: List[int] = Field(default_factory=list)
    scene_feedback: Dict[int, SceneFeedbackItem] = Field(default_factory=dict)
    decision: str = "APPROVED"  # APPROVED or CHANGES_REQUESTED
    is_operator_review: bool = True  # Invariant: Must be verified real operator action
    approved_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ProductionRun(BaseModel):
    id: str
    video_project_id: Optional[str] = None
    channel_profile_id: Optional[str] = None
    run_environment: RunEnvironment = Field(default=RunEnvironment.DEV)
    status: ProductionRunStatus = ProductionRunStatus.CREATED
    mode: str = "auto"
    request: AutoVideoRequest
    current_stage: Optional[str] = None
    progress_pct: int = 0
    quality_score: Optional[float] = None
    blocker_count: int = 0
    error_message: Optional[str] = None
    first_pass_qc_pass: Optional[bool] = None
    first_pass_human_approval: Optional[bool] = None
    stages: List[ProductionStageRun] = Field(default_factory=list)
    fact_pack: Optional[FactPack] = None
    story_plan: Optional[StoryPlan] = None
    original_script_plan: Optional[ScriptPlan] = None
    script_plan: Optional[ScriptPlan] = None
    script_gate_report: Optional[ScriptQualityGateReport] = None
    visual_plan: Optional[VisualPlan] = None
    resolved_assets: Optional[AssetResolutionResult] = None
    editor_plan: Optional[EditorPlan] = None
    quality_report: Optional[QualityReport] = None
    output_video_url: Optional[str] = None
    render_artifact: Optional[RenderArtifact] = None
    auto_fix_history: List[Dict[str, Any]] = Field(default_factory=list)
    manual_interventions: List[ManualInterventionRecord] = Field(default_factory=list)
    visual_ground_truth: List[VisualReplacementGroundTruth] = Field(default_factory=list)
    script_diff_ground_truth: Optional[ScriptDiffGroundTruth] = None
    human_review: Optional[HumanReviewRecord] = None
    publication_status: PublicationStatus = PublicationStatus.NOT_APPROVED
    cost_telemetry: Optional[CostTelemetry] = None
    latency_telemetry: Optional[LatencyTelemetry] = None
    provider_execution: Dict[str, str] = Field(default_factory=dict)
    storage_tier: StorageTier = StorageTier.FINAL
    idempotency_key: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def manual_intervention_count(self) -> int:
        return sum(1 for item in self.manual_interventions if item.intervention_source == InterventionSource.REAL_OPERATOR)

    @property
    def manual_intervention_rate(self) -> float:
        total_scenes = len(self.script_plan.scenes) if (self.script_plan and self.script_plan.scenes) else 1
        return round(self.manual_intervention_count / max(1, total_scenes), 2)

    @property
    def full_provider_e2e(self) -> bool:
        """True only when recorded applicable providers are neither mock nor fixtures."""
        if not self.provider_execution:
            return False
        invalid = {"MOCK", "SIMULATION", "FIXTURE", "LEXICAL_FALLBACK", "GENERIC_FALLBACK", "METADATA_ONLY"}
        return not any(str(mode).upper() in invalid for mode in self.provider_execution.values())

    @property
    def full_live_e2e(self) -> bool:
        return self.full_provider_e2e

    @property
    def real_user_source_count(self) -> int:
        return sum(1 for source in self.request.sources if source.provenance.upper() == "USER")

    @property
    def fixture_source_count(self) -> int:
        return sum(1 for source in self.request.sources if source.provenance.upper() == "FIXTURE")
