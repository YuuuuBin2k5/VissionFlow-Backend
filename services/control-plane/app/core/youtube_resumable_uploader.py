"""
YouTube Data API v3 Resumable Upload adapter for VisionFlow.

Performs a resumable multipart upload directly against the YouTube Data API,
avoiding any browser/Playwright dependency. This module only needs `requests`
(already a Control Plane dependency).

Reference: https://developers.google.com/youtube/v3/docs/videos/insert
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_UPLOAD_ENDPOINT = "https://www.googleapis.com/upload/youtube/v3/videos"
_CHUNK_SIZE = 8 * 1024 * 1024  # 8 MiB


@dataclass(frozen=True)
class YouTubeUploadMetadata:
    title: str
    description: str
    tags: tuple[str, ...]
    privacy_status: str          # "public" | "private" | "unlisted"
    category_id: str = "28"      # Science & Technology
    default_language: str = "vi"
    self_declared_made_for_kids: bool = False
    publish_at_iso: Optional[str] = None
    embeddable: bool = True
    license: str = "youtube"


@dataclass(frozen=True)
class YouTubeUploadResult:
    video_id: str
    url: str


class YouTubeResumableUploader:
    """Upload a local MP4 to YouTube via the Data API v3 resumable protocol."""

    def __init__(self, session: object) -> None:
        self._session = session

    def upload(
        self,
        access_token: str,
        video_path: Path,
        metadata: YouTubeUploadMetadata,
        thumbnail_path: Optional[Path] = None,
    ) -> YouTubeUploadResult:
        uri = self._initiate_resumable_upload(access_token, video_path, metadata)
        video_id = self._stream_file(uri, access_token, video_path)
        url = f"https://www.youtube.com/watch?v={video_id}"
        if thumbnail_path and thumbnail_path.exists():
            try:
                self.set_thumbnail(access_token, video_id, thumbnail_path)
            except Exception as thumb_err:
                logger.warning("Failed to set thumbnail for %s: %s", video_id, thumb_err)
        return YouTubeUploadResult(video_id=video_id, url=url)

    def set_thumbnail(
        self,
        access_token: str,
        video_id: str,
        image_path: Path,
    ) -> bool:
        """
        Upload and set a custom thumbnail for an existing YouTube video.
        
        Reference: https://developers.google.com/youtube/v3/docs/thumbnails/set
        Endpoint: POST https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={videoId}
        Supported formats: image/jpeg, image/png (max 2MB)
        """
        if not image_path.exists():
            logger.warning("Thumbnail file does not exist: %s", image_path)
            return False

        content_type = "image/jpeg"
        if image_path.suffix.lower() == ".png":
            content_type = "image/png"

        url = f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={video_id}"
        file_size = image_path.stat().st_size
        logger.info(
            "Uploading custom thumbnail for YouTube video %s (%d bytes, %s)",
            video_id, file_size, content_type
        )

        with open(image_path, "rb") as fh:
            image_data = fh.read()

        resp = self._session.post(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": content_type,
            },
            data=image_data,
            timeout=(15, 60),
        )

        if resp.status_code in (200, 201):
            logger.info("Successfully set custom thumbnail for YouTube video %s!", video_id)
            return True
        else:
            logger.warning(
                "YouTube set_thumbnail returned %s: %s (Note: channel may need phone verification for custom thumbnails)",
                resp.status_code,
                resp.text[:300],
            )
            return False

    def _build_resource(self, metadata: YouTubeUploadMetadata) -> dict:
        if metadata.privacy_status not in {"unlisted", "private"}:
            raise ValueError("YouTube uploads must use unlisted or private visibility")
        status: dict = {"privacyStatus": metadata.privacy_status}
        if metadata.publish_at_iso and metadata.privacy_status == "private":
            status["publishAt"] = metadata.publish_at_iso
        return {
            "snippet": {
                "title": metadata.title[:100],
                "description": metadata.description[:5000],
                "tags": list(metadata.tags),
                "categoryId": metadata.category_id,
                "defaultLanguage": metadata.default_language,
            },
            "status": {
                **status,
                "selfDeclaredMadeForKids": metadata.self_declared_made_for_kids,
                "embeddable": metadata.embeddable,
                "license": metadata.license,
            },
        }

    def _initiate_resumable_upload(
        self,
        access_token: str,
        video_path: Path,
        metadata: YouTubeUploadMetadata,
    ) -> str:
        file_size = video_path.stat().st_size
        resource = self._build_resource(metadata)

        resp = self._session.post(
            _UPLOAD_ENDPOINT,
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "video/mp4",
                "X-Upload-Content-Length": str(file_size),
            },
            data=json.dumps(resource).encode("utf-8"),
            timeout=(10, 30),
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"YouTube resumable init failed {resp.status_code}: {resp.text[:400]}"
            )
        upload_uri = resp.headers.get("Location")
        if not upload_uri:
            raise RuntimeError("YouTube did not return a Location header for resumable upload")
        logger.info("Resumable upload session started: %s", upload_uri[:80])
        return upload_uri

    def _stream_file(
        self, upload_uri: str, access_token: str, video_path: Path
    ) -> str:
        file_size = video_path.stat().st_size
        offset = 0

        with open(video_path, "rb") as fh:
            while offset < file_size:
                chunk_data = fh.read(_CHUNK_SIZE)
                chunk_len = len(chunk_data)
                end_byte = offset + chunk_len - 1

                logger.info(
                    "Uploading bytes %d-%d / %d (%.1f%%)",
                    offset, end_byte, file_size, (end_byte + 1) / file_size * 100,
                )

                resp = self._session.put(
                    upload_uri,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "video/mp4",
                        "Content-Length": str(chunk_len),
                        "Content-Range": f"bytes {offset}-{end_byte}/{file_size}",
                    },
                    data=chunk_data,
                    timeout=(30, 300),
                )

                if resp.status_code in (200, 201):
                    data = resp.json()
                    video_id = data.get("id")
                    if not video_id:
                        raise RuntimeError(
                            f"YouTube upload complete but no video ID returned: {resp.text[:200]}"
                        )
                    logger.info("YouTube upload complete! video_id=%s", video_id)
                    return video_id

                if resp.status_code == 308:
                    range_header = resp.headers.get("Range", "")
                    if range_header:
                        offset = int(range_header.split("-")[-1]) + 1
                    else:
                        offset += chunk_len
                    continue

                raise RuntimeError(
                    f"YouTube chunk upload failed {resp.status_code}: {resp.text[:400]}"
                )

        raise RuntimeError("File exhausted without YouTube confirming completion")
