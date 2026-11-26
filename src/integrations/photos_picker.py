"""Google Photos Picker API v1 Client mit sicherem Streaming-Download."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import requests

from src.config.constants import (
    DEFAULT_HTTP_TIMEOUT_SECONDS,
    DEFAULT_PICKER_MAX_ITEMS,
    MAX_VIDEO_FILE_SIZE_BYTES,
    MEDIA_DOWNLOAD_TIMEOUT_SECONDS,
    PHOTOS_PICKER_API_BASE,
    STREAM_READ_CHUNK_SIZE_BYTES,
)
from src.domain.exceptions import InputValidationError, PhotosPickerError
from src.domain.models import PickedVideoItem, PickerSessionInfo
from src.security.google_oauth import GoogleOAuthCredentialProvider
from src.security.sanitization import (
    get_safe_filepath,
    sanitize_filename,
    validate_google_media_url,
)

logger = logging.getLogger(__name__)


def _parse_poll_interval(session_data: dict[str, Any]) -> float:
    polling_cfg = session_data.get("pollingConfig")
    if not isinstance(polling_cfg, dict):
        return 3.0
    raw_interval = str(polling_cfg.get("pollInterval") or "3s").strip().rstrip("s")
    try:
        return max(1.0, float(raw_interval))
    except ValueError:
        return 3.0


def _parse_session(data: dict[str, Any]) -> PickerSessionInfo:
    session_id = str(data.get("id") or "").strip()
    picker_uri = str(data.get("pickerUri") or "").strip()
    if not session_id or not picker_uri:
        raise PhotosPickerError("Ungültige Picker-Session-Antwort der Google API.")
    return PickerSessionInfo(
        session_id=session_id,
        picker_uri=picker_uri,
        media_items_set=bool(data.get("mediaItemsSet", False)),
        expire_time=str(data.get("expireTime")) if data.get("expireTime") else None,
        poll_interval_seconds=_parse_poll_interval(data),
    )


class GooglePhotosPickerClient:
    """Kapselt Session-Management und Video-Download über die Photos Picker API v1."""

    def __init__(
        self,
        credential_provider: GoogleOAuthCredentialProvider,
        session: requests.Session | None = None,
    ) -> None:
        self._creds = credential_provider
        self._http = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        token = self._creds.get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    def create_session(self, max_item_count: int = DEFAULT_PICKER_MAX_ITEMS) -> PickerSessionInfo:
        """Startet eine neue Google Photos Picker Session und liefert die `pickerUri`."""
        payload = {"pickingConfig": {"maxItemCount": max(1, int(max_item_count))}}
        try:
            resp = self._http.post(
                f"{PHOTOS_PICKER_API_BASE}/sessions",
                headers=self._headers(),
                json=payload,
                timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise PhotosPickerError(f"Photos Picker Session konnte nicht erstellt werden: {exc}") from exc

        if resp.status_code not in {200, 201}:
            raise PhotosPickerError(
                f"Photos Picker API Fehler HTTP {resp.status_code} beim Erstellen der Session."
            )
        return _parse_session(resp.json())

    def get_session(self, session_id: str) -> PickerSessionInfo:
        """Fragt den aktuellen Auswahlstatus einer Picker-Session ab."""
        clean_id = session_id.strip()
        if not clean_id:
            raise InputValidationError("Leere Picker-Session-ID.")
        try:
            resp = self._http.get(
                f"{PHOTOS_PICKER_API_BASE}/sessions/{clean_id}",
                headers=self._headers(),
                timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise PhotosPickerError(f"Statusabfrage der Picker-Session fehlgeschlagen: {exc}") from exc

        if resp.status_code != 200:
            raise PhotosPickerError(f"Picker-Session-Abruf fehlgeschlagen (HTTP {resp.status_code}).")
        return _parse_session(resp.json())

    def list_video_items(self, session_id: str) -> list[PickedVideoItem]:
        """Listet alle vom Nutzer ausgewählten Videos (`type == 'VIDEO'`) paginiert auf."""
        clean_id = session_id.strip()
        if not clean_id:
            raise InputValidationError("Leere Picker-Session-ID.")

        items: list[PickedVideoItem] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {"sessionId": clean_id, "pageSize": 100}
            if page_token:
                params["pageToken"] = page_token
            try:
                resp = self._http.get(
                    f"{PHOTOS_PICKER_API_BASE}/mediaItems",
                    headers=self._headers(),
                    params=params,
                    timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
                )
            except requests.RequestException as exc:
                raise PhotosPickerError(f"Fehler beim Listen der Picker-Medien: {exc}") from exc

            if resp.status_code != 200:
                raise PhotosPickerError(f"Picker mediaItems.list Fehler HTTP {resp.status_code}.")

            data = resp.json()
            for raw in data.get("mediaItems") or []:
                if not isinstance(raw, dict) or str(raw.get("type") or "").upper() != "VIDEO":
                    continue
                media_file = raw.get("mediaFile")
                if not isinstance(media_file, dict):
                    continue
                base_url = str(media_file.get("baseUrl") or "").strip()
                if not base_url:
                    continue
                meta = media_file.get("mediaFileMetadata") or {}
                video_meta = meta.get("videoMetadata") if isinstance(meta, dict) else {}
                fps_raw = video_meta.get("fps") if isinstance(video_meta, dict) else None
                proc_status = (
                    str(video_meta.get("processingStatus") or "READY")
                    if isinstance(video_meta, dict)
                    else "READY"
                )
                items.append(
                    PickedVideoItem(
                        media_id=str(raw.get("id") or ""),
                        filename=sanitize_filename(
                            str(media_file.get("filename") or f"{raw.get('id')}.mp4")
                        ),
                        mime_type=str(media_file.get("mimeType") or "video/mp4"),
                        base_url=base_url,
                        create_time=str(raw.get("createTime")) if raw.get("createTime") else None,
                        fps=float(fps_raw) if fps_raw is not None else None,
                        processing_status=proc_status,
                    )
                )

            page_token = data.get("nextPageToken")
            if not page_token:
                break

        return items

    def delete_session(self, session_id: str) -> None:
        """Bereinigt eine abgeschlossene Picker-Session auf Google-Seite."""
        clean_id = session_id.strip()
        if not clean_id:
            return
        try:
            resp = self._http.delete(
                f"{PHOTOS_PICKER_API_BASE}/sessions/{clean_id}",
                headers=self._headers(),
                timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
            )
            if resp.status_code not in {200, 204, 404}:
                logger.warning("Picker-Session Cleanup lieferte HTTP %d.", resp.status_code)
        except requests.RequestException as exc:
            logger.warning("Picker-Session Cleanup fehlgeschlagen: %s", exc)

    def download_video_to_path(
        self,
        item: PickedVideoItem,
        target_dir: Path,
        max_bytes: int = MAX_VIDEO_FILE_SIZE_BYTES,
    ) -> Path:
        """Lädt das gewählte Video per HTTPS + Host-Whitelist im Chunk-Streaming herunter."""
        validated_base = validate_google_media_url(item.base_url)
        download_url = validated_base if validated_base.endswith("=dv") else f"{validated_base}=dv"
        target_path = get_safe_filepath(target_dir, item.filename)

        try:
            with self._http.get(
                download_url,
                headers={"Authorization": f"Bearer {self._creds.get_access_token()}"},
                stream=True,
                timeout=MEDIA_DOWNLOAD_TIMEOUT_SECONDS,
            ) as resp:
                if resp.status_code != 200:
                    raise PhotosPickerError(
                        f"Video-Download fehlgeschlagen (HTTP {resp.status_code}) für '{item.filename}'."
                    )
                total_bytes = 0
                with target_path.open("wb") as handle:
                    for chunk in resp.iter_content(chunk_size=STREAM_READ_CHUNK_SIZE_BYTES):
                        if not chunk:
                            continue
                        total_bytes += len(chunk)
                        if total_bytes > max_bytes:
                            raise PhotosPickerError(
                                f"Video '{item.filename}' überschreitet das Größenlimit von {max_bytes} Bytes."
                            )
                        handle.write(chunk)
        except PhotosPickerError:
            if target_path.exists():
                target_path.unlink(missing_ok=True)
            raise
        except requests.RequestException as exc:
            if target_path.exists():
                target_path.unlink(missing_ok=True)
            raise PhotosPickerError(f"Netzwerkfehler beim Video-Download: {exc}") from exc

        return target_path
