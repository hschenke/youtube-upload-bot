"""Google Drive API v3 Staging-Client für Video-Queue, Download und Papierkorb-Cleanup."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from src.config.constants import (
    DEFAULT_STAGING_FOLDER_NAME,
    DRIVE_CHUNK_SIZE_BYTES,
    MAX_VIDEO_FILE_SIZE_BYTES,
)
from src.domain.exceptions import DriveStagingError
from src.domain.models import DriveVideoFile
from src.security.google_oauth import GoogleOAuthCredentialProvider
from src.security.sanitization import get_safe_filepath, sanitize_filename

logger = logging.getLogger(__name__)
_DRIVE_FILE_FIELDS = (
    "id, name, mimeType, size, createdTime, modifiedTime, trashed, "
    "videoMediaMetadata, appProperties"
)


def _escape_drive_query_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _parse_drive_video(raw: dict[str, Any]) -> DriveVideoFile:
    v_meta = raw.get("videoMediaMetadata") or {}
    props = raw.get("appProperties") or {}
    duration_ms = v_meta.get("durationMillis") if isinstance(v_meta, dict) else None
    duration_sec = round(float(duration_ms) / 1000.0, 3) if duration_ms is not None else None
    width = int(v_meta["width"]) if isinstance(v_meta, dict) and v_meta.get("width") else None
    height = int(v_meta["height"]) if isinstance(v_meta, dict) and v_meta.get("height") else None

    return DriveVideoFile(
        drive_file_id=str(raw["id"]),
        filename=sanitize_filename(str(raw.get("name") or f"{raw['id']}.mp4")),
        mime_type=str(raw.get("mimeType") or "video/mp4"),
        size_bytes=int(raw.get("size") or 0),
        created_time=str(raw["createdTime"]) if raw.get("createdTime") else None,
        modified_time=str(raw["modifiedTime"]) if raw.get("modifiedTime") else None,
        width=width,
        height=height,
        duration_seconds=duration_sec,
        photos_media_id=(
            str(props["photos_media_id"])
            if isinstance(props, dict) and props.get("photos_media_id")
            else None
        ),
        original_created_at=(
            str(props["original_created_at"])
            if isinstance(props, dict) and props.get("original_created_at")
            else None
        ),
        trashed=bool(raw.get("trashed", False)),
    )


class GoogleDriveStagingClient:
    """Verwaltet gestagte Videos in einem dedizierten Google-Drive-Ordner."""

    def __init__(
        self,
        credential_provider: GoogleOAuthCredentialProvider,
        folder_id: str = "",
        folder_name: str = DEFAULT_STAGING_FOLDER_NAME,
        service: Any = None,
    ) -> None:
        self._creds = credential_provider
        self._folder_id = folder_id.strip()
        self._folder_name = folder_name.strip() or DEFAULT_STAGING_FOLDER_NAME
        self._service = service

    def _get_service(self) -> Any:
        if self._service is not None:
            return self._service
        return build(
            "drive",
            "v3",
            credentials=self._creds.get_credentials(),
            cache_discovery=False,
        )

    def ensure_staging_folder(self) -> str:
        """Liefert die konfigurierte Ordner-ID oder sucht/erstellt den Staging-Ordner."""
        if self._folder_id:
            return self._folder_id

        service = self._get_service()
        escaped_name = _escape_drive_query_literal(self._folder_name)
        query = (
            f"name = '{escaped_name}' and "
            "mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        )
        try:
            res = (
                service.files()
                .list(q=query, fields="files(id, name)", pageSize=5, spaces="drive")
                .execute()
            )
            files = res.get("files") or []
            if files:
                self._folder_id = str(files[0]["id"])
                return self._folder_id

            created = (
                service.files()
                .create(
                    body={
                        "name": self._folder_name,
                        "mimeType": "application/vnd.google-apps.folder",
                    },
                    fields="id",
                )
                .execute()
            )
            self._folder_id = str(created["id"])
            logger.info("Google Drive Staging-Ordner '%s' erstellt (%s).", self._folder_name, self._folder_id)
            return self._folder_id
        except HttpError as exc:
            raise DriveStagingError(f"Google Drive Ordner-Zugriff fehlgeschlagen: {exc}") from exc

    def list_staged_videos(self, folder_id: str | None = None) -> list[DriveVideoFile]:
        """Listet alle ungelöschten Videodateien im Staging-Ordner paginiert auf."""
        target_folder = (folder_id or self.ensure_staging_folder()).strip()
        escaped_id = _escape_drive_query_literal(target_folder)
        query = (
            f"'{escaped_id}' in parents and trashed = false and mimeType contains 'video/'"
        )

        service = self._get_service()
        videos: list[DriveVideoFile] = []
        page_token: str | None = None
        try:
            while True:
                res = (
                    service.files()
                    .list(
                        q=query,
                        fields=f"nextPageToken, files({_DRIVE_FILE_FIELDS})",
                        pageSize=100,
                        pageToken=page_token,
                        spaces="drive",
                    )
                    .execute()
                )
                for raw in res.get("files") or []:
                    if isinstance(raw, dict) and raw.get("id"):
                        videos.append(_parse_drive_video(raw))
                page_token = res.get("nextPageToken")
                if not page_token:
                    break
        except HttpError as exc:
            raise DriveStagingError(f"Fehler beim Listen des Drive Staging-Ordners: {exc}") from exc

        return videos

    def upload_video_file(
        self,
        local_path: Path,
        *,
        filename: str,
        mime_type: str = "video/mp4",
        folder_id: str | None = None,
        photos_media_id: str | None = None,
        original_created_at: str | None = None,
    ) -> DriveVideoFile:
        """Lädt ein Video per Resumable Upload mit Metadaten-Properties in den Staging-Ordner."""
        if not local_path.exists():
            raise DriveStagingError(f"Lokale Datei nicht gefunden: {local_path.name}")

        target_folder = (folder_id or self.ensure_staging_folder()).strip()
        safe_name = sanitize_filename(filename)
        app_props: dict[str, str] = {"source_filename": safe_name}
        if photos_media_id:
            app_props["photos_media_id"] = photos_media_id[:120]
        if original_created_at:
            app_props["original_created_at"] = original_created_at[:64]

        body: dict[str, Any] = {
            "name": safe_name,
            "parents": [target_folder],
            "appProperties": app_props,
        }
        media = MediaFileUpload(
            str(local_path),
            mimetype=mime_type or "video/mp4",
            chunksize=DRIVE_CHUNK_SIZE_BYTES,
            resumable=True,
        )
        service = self._get_service()
        try:
            request = service.files().create(
                body=body,
                media_body=media,
                fields=_DRIVE_FILE_FIELDS,
            )
            response = None
            while response is None:
                _, response = request.next_chunk()
            return _parse_drive_video(response)
        except HttpError as exc:
            raise DriveStagingError(f"Drive-Upload fehlgeschlagen für '{safe_name}': {exc}") from exc

    def download_video_to_path(
        self,
        drive_file_id: str,
        filename: str,
        target_dir: Path,
        max_bytes: int = MAX_VIDEO_FILE_SIZE_BYTES,
    ) -> Path:
        """Lädt ein Video aus Drive im Chunk-Streaming sicher in `target_dir`."""
        target_path = get_safe_filepath(target_dir, filename)
        service = self._get_service()
        request = service.files().get_media(fileId=drive_file_id)

        try:
            with target_path.open("wb") as handle:
                downloader = MediaIoBaseDownload(
                    handle,
                    request,
                    chunksize=DRIVE_CHUNK_SIZE_BYTES,
                )
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                    if target_path.stat().st_size > max_bytes:
                        raise DriveStagingError(
                            f"Drive-Datei '{filename}' überschreitet das Limit von {max_bytes} Bytes."
                        )
        except DriveStagingError:
            target_path.unlink(missing_ok=True)
            raise
        except HttpError as exc:
            target_path.unlink(missing_ok=True)
            raise DriveStagingError(f"Drive-Download fehlgeschlagen für '{filename}': {exc}") from exc

        return target_path

    def trash_file(self, drive_file_id: str) -> None:
        """Verschiebt die Drive-Kopie nach erfolgreichem YouTube-Upload in den Papierkorb."""
        service = self._get_service()
        try:
            service.files().update(
                fileId=drive_file_id,
                body={"trashed": True},
                fields="id, trashed",
            ).execute()
            logger.info("Drive-Staging-Datei '%s' in den Papierkorb verschoben.", drive_file_id)
        except HttpError as exc:
            raise DriveStagingError(
                f"Drive-Datei '{drive_file_id}' konnte nicht in den Papierkorb verschoben werden: {exc}"
            ) from exc
