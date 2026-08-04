"""YouTube Data API resumable-upload adapter; no legacy browser or database access."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class HttpResponse(Protocol):
    status_code: int
    headers: dict[str, str]
    def json(self) -> object: ...


class HttpClient(Protocol):
    def post(self, url: str, **kwargs: object) -> HttpResponse: ...
    def put(self, url: str, **kwargs: object) -> HttpResponse: ...


@dataclass(frozen=True)
class YouTubeUploadMetadata:
    title: str
    description: str
    tags: tuple[str, ...]
    privacy_status: str = "unlisted"
    publish_at_iso: str | None = None
    self_declared_made_for_kids: bool = False
    category_id: str = "28"  # Science & Technology (24 = Entertainment)
    default_language: str = "vi"
    embeddable: bool = True
    license: str = "youtube"


@dataclass(frozen=True)
class YouTubeUploadResult:
    video_id: str
    url: str


class YouTubeResumableUploader:
    """Upload a local final export through ``videos.insert`` resumable sessions."""

    _INIT_URL = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def upload(self, *, access_token: str, video_path: Path, metadata: YouTubeUploadMetadata) -> YouTubeUploadResult:
        if not access_token.strip():
            raise ValueError("access_token is required")
        if not video_path.is_file() or video_path.suffix.lower() not in {".mp4", ".mov", ".webm"}:
            raise ValueError("video_path must be a readable video export")

        snippet = {
            "title": metadata.title,
            "description": metadata.description,
            "tags": list(metadata.tags),
            "categoryId": metadata.category_id,
            "defaultLanguage": metadata.default_language,
            "defaultAudioLanguage": metadata.default_language,
        }

        status = {
            "selfDeclaredMadeForKids": metadata.self_declared_made_for_kids,
            "embeddable": metadata.embeddable,
            "license": metadata.license,
            "privacyStatus": "unlisted",  # Always force unlisted mode per user preference
        }

        body = {
            "snippet": snippet,
            "status": status,
        }
        size = video_path.stat().st_size
        init = self._http.post(self._INIT_URL, headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=UTF-8", "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/mp4"}, json=body, timeout=(5, 30))
        upload_url = init.headers.get("Location")
        if init.status_code not in {200, 201} or not upload_url:
            raise RuntimeError("YouTube resumable session could not be created")
        with video_path.open("rb") as stream:
            completed = self._http.put(upload_url, headers={"Authorization": f"Bearer {access_token}", "Content-Length": str(size), "Content-Type": "video/mp4"}, data=stream, timeout=(10, 600))
        data = completed.json() if completed.status_code in {200, 201} else {}
        video_id = data.get("id") if isinstance(data, dict) else None
        if not isinstance(video_id, str) or not video_id:
            raise RuntimeError("YouTube upload did not return a video id")
        return YouTubeUploadResult(video_id=video_id, url=f"https://www.youtube.com/watch?v={video_id}")
