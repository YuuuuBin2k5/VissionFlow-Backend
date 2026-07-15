from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RenderMode(str, Enum):
    STANDARD = "standard"
    SPLIT_SCREEN_SHORT = "split_screen_short"
    MUSIC_REACTIVE = "music_reactive"
    MUSIC_REMIX_REACTIVE = "music_remix_reactive"
    TRANSLATE_DUB = "translate_dub"


class RenderStopStage(str, Enum):
    SCRIPT = "script"
    AUDIO = "audio"
    ASSETS = "assets"
    VIDEO = "video"
    PUBLISH = "publish"


@dataclass(frozen=True)
class RenderContract:
    job_id: int
    title: str
    topic: str
    audience: str
    mode: RenderMode = RenderMode.STANDARD
    stop_at: RenderStopStage = RenderStopStage.VIDEO
    voice_code: str = "edge-nam-minh"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_split_screen(self) -> bool:
        return self.mode == RenderMode.SPLIT_SCREEN_SHORT

    @property
    def is_music_reactive(self) -> bool:
        return self.mode in {RenderMode.MUSIC_REACTIVE, RenderMode.MUSIC_REMIX_REACTIVE}

    @property
    def is_translate_dub(self) -> bool:
        return self.mode == RenderMode.TRANSLATE_DUB


def resolve_render_mode(job: dict, metadata: dict[str, Any]) -> RenderMode:
    raw_mode = str(metadata.get("render_mode") or "").strip()
    title = str(job.get("video_title_idea") or "").strip().lower()

    if raw_mode == RenderMode.TRANSLATE_DUB.value or title.startswith("[dub]"):
        return RenderMode.TRANSLATE_DUB
    if raw_mode == RenderMode.SPLIT_SCREEN_SHORT.value:
        return RenderMode.SPLIT_SCREEN_SHORT
    if raw_mode == RenderMode.MUSIC_REMIX_REACTIVE.value:
        return RenderMode.MUSIC_REMIX_REACTIVE
    if (
        raw_mode == RenderMode.MUSIC_REACTIVE.value
        or metadata.get("is_standalone_music_video") is True
        or metadata.get("requires_user_audio") is True
    ):
        return RenderMode.MUSIC_REACTIVE
    return RenderMode.STANDARD


def build_render_contract(
    job: dict,
    metadata: dict[str, Any],
    topic: str,
    audience: str,
    voice_code: str = "edge-nam-minh",
    stop_at: RenderStopStage = RenderStopStage.VIDEO,
) -> RenderContract:
    return RenderContract(
        job_id=int(job["id"]),
        title=str(job.get("video_title_idea") or f"Video #{job['id']}"),
        topic=str(topic or ""),
        audience=str(audience or "Moi doi tuong"),
        mode=resolve_render_mode(job, metadata),
        stop_at=stop_at,
        voice_code=voice_code or "edge-nam-minh",
        metadata=dict(metadata or {}),
    )
