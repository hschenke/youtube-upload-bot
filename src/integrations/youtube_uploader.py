"""YouTube Data API v3 Resumable Upload Client."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from src.config.constants import (
    RETRY_BACKOFF_BASE_SECONDS,
    YOUTUBE_CHUNK_SIZE_BYTES,
    YOUTUBE_DEFAULT_CATEGORY_ID,
    YOUTUBE_MAX_TAG_CHARS,
    YOUTUBE_SHORTS_URL_TEMPLATE,
    YOUTUBE_UPLOAD_MAX_RETRIES,
    YOUTUBE_WATCH_URL_TEMPLATE,
)
from src.domain.enums import PrivacyStatus
from src.domain.exceptions import YouTubeUploadError
from src.domain.models import UploadResult
from src.domain.schemas import GeneratedVideoMetadata
from src.security.google_oauth import GoogleOAuthCredentialProvider
from src.security.sanitization import sanitize_youtube_description, sanitize_youtube_title

logger = logging.getLogger(__name__)
_RETRIABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _pack_tags(raw_tags: list[str], max_total_chars: int = YOUTUBE_MAX_TAG_CHARS) -> list[str]:
    packed: list[str] = []
    running_len = 0
    for tag in raw_tags:
        clean = tag.strip().lstrip("#")
        if not clean:
            continue
        extra = len(clean) + (1 if packed else 0)
        if running_len + extra > max_total_chars:
            break
        packed.append(clean)
        running_len += extra
    return packed


class YouTubeUploaderClient:
    """Lädt Videos mit Resumable Upload und Metadaten über die YouTube Data API v3 hoch."""

    def __init__(
        self,
        credential_provider: GoogleOAuthCredentialProvider,
        service: Any = None,
    ) -> None:
        self._creds = credential_provider
        self._service = service

    def _get_service(self) -> Any:
        if self._service is not None:
            return self._service
        return build(
            "youtube",
            "v3",
            credentials=self._creds.get_credentials(),
            cache_discovery=False,
        )

    def get_channel_info(self) -> dict[str, Any] | None:
        """Liest Basis-Metadaten des authentifizierten YouTube-Kanals für den System-Check."""
        service = self._get_service()
        try:
            res = service.channels().list(part="snippet,statistics", mine=True).execute()
            items = res.get("items") or []
            if not items:
                return None
            channel = items[0]
            snippet = channel.get("snippet") or {}
            stats = channel.get("statistics") or {}
            return {
                "id": str(channel.get("id") or ""),
                "title": str(snippet.get("title") or "Unbekannter Kanal"),
                "subscriber_count": str(stats.get("subscriberCount") or "0"),
                "video_count": str(stats.get("videoCount") or "0"),
            }
        except HttpError as exc:
            raise YouTubeUploadError(f"YouTube-Kanalabruf fehlgeschlagen: {exc}") from exc

    def upload_video(
        self,
        local_path: Path,
        *,
        metadata: GeneratedVideoMetadata,
        privacy_status: PrivacyStatus = PrivacyStatus.PUBLIC,
        category_id: str = YOUTUBE_DEFAULT_CATEGORY_ID,
        made_for_kids: bool = False,
        is_short: bool = True,
    ) -> UploadResult:
        """Lädt `local_path` über `videos.insert` hoch und gibt die YouTube-URL zurück."""
        if not local_path.exists():
            raise YouTubeUploadError(f"Lokale Videodatei fehlt für Upload: {local_path.name}")

        clean_title = sanitize_youtube_title(metadata.title)
        clean_description = sanitize_youtube_description(metadata.description)
        packed_tags = _pack_tags(metadata.tags)

        request_body: dict[str, Any] = {
            "snippet": {
                "title": clean_title,
                "description": clean_description,
                "tags": packed_tags,
                "categoryId": category_id or YOUTUBE_DEFAULT_CATEGORY_ID,
            },
            "status": {
                "privacyStatus": privacy_status.value,
                "selfDeclaredMadeForKids": bool(made_for_kids),
            },
        }
        media = MediaFileUpload(
            str(local_path),
            chunksize=YOUTUBE_CHUNK_SIZE_BYTES,
            resumable=True,
        )

        service = self._get_service()
        try:
            insert_request = service.videos().insert(
                part="snippet,status",
                body=request_body,
                media_body=media,
            )
            response = self._execute_resumable_with_retry(insert_request)
        except HttpError as exc:
            raise YouTubeUploadError(f"YouTube API Upload fehlgeschlagen: {exc}") from exc

        video_id = str((response or {}).get("id") or "").strip()
        if not video_id:
            raise YouTubeUploadError("YouTube API lieferte keine Video-ID zurück.")

        url_template = YOUTUBE_SHORTS_URL_TEMPLATE if is_short else YOUTUBE_WATCH_URL_TEMPLATE
        youtube_url = url_template.format(video_id=video_id)
        logger.info("YouTube-Upload erfolgreich: %s (%s)", video_id, youtube_url)
        return UploadResult(
            video_id=video_id,
            youtube_url=youtube_url,
            title=clean_title,
            description=clean_description,
            tags=tuple(packed_tags),
            privacy_status=privacy_status,
        )

    @staticmethod
    def _execute_resumable_with_retry(request: Any) -> dict[str, Any]:
        response = None
        retries = 0
        while response is None:
            try:
                _, response = request.next_chunk()
            except HttpError as exc:
                status_code = getattr(exc.resp, "status", None)
                if status_code in _RETRIABLE_STATUS_CODES and retries < YOUTUBE_UPLOAD_MAX_RETRIES:
                    retries += 1
                    wait_sec = RETRY_BACKOFF_BASE_SECONDS * (2 ** (retries - 1))
                    logger.warning(
                        "Transientes YouTube HTTP %s beim Chunk-Upload – Retry %d/%d in %.1fs.",
                        status_code,
                        retries,
                        YOUTUBE_UPLOAD_MAX_RETRIES,
                        wait_sec,
                    )
                    time.sleep(wait_sec)
                    continue
                raise
        return response
