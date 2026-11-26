"""Unveränderliche Domänen-Dataclasses für den gesamten Bot-Lebenszyklus."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.domain.enums import (
    PrivacyStatus,
    RunStatus,
    SelectionOrder,
    TriggerSource,
    VideoOrientation,
    VideoQueueStatus,
)


@dataclass(frozen=True)
class UploadProfile:
    """Regelwerk für Video-Filterung, Zeitschema, YouTube-Defaults und KI-Prompts."""

    name: str
    display_name: str
    enabled: bool = True
    orientation: VideoOrientation = VideoOrientation.PORTRAIT
    min_aspect_ratio: float | None = 0.45
    max_aspect_ratio: float | None = 0.85
    min_duration_seconds: float | None = 3.0
    max_duration_seconds: float | None = 180.0
    min_width: int | None = 360
    min_height: int | None = 640
    date_from: str | None = None
    date_to: str | None = None
    include_filename_patterns: tuple[str, ...] = ()
    exclude_filename_patterns: tuple[str, ...] = ()
    selection_order: SelectionOrder = SelectionOrder.OLDEST_FIRST
    max_uploads_per_run: int = 1
    privacy_status: PrivacyStatus = PrivacyStatus.PUBLIC
    category_id: str = "22"
    made_for_kids: bool = False
    language: str = "en"
    required_hashtags: tuple[str, ...] = ("#Shorts",)
    default_tags: tuple[str, ...] = ("shorts",)
    description_footer: str = ""
    ai_prompt: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class MediaProbeResult:
    """Ergebnis der exakten Video-Inspektion inklusive effektiver Anzeige-Rotation."""

    raw_width: int
    raw_height: int
    display_width: int
    display_height: int
    rotation_degrees: int
    duration_seconds: float
    fps: float | None = None
    video_codec: str = ""
    has_audio: bool = True
    creation_time: str | None = None
    file_size_bytes: int = 0

    @property
    def aspect_ratio(self) -> float:
        if self.display_height <= 0:
            return 0.0
        return round(self.display_width / self.display_height, 4)


@dataclass(frozen=True)
class PickerSessionInfo:
    """Status einer Google Photos Picker API Session."""

    session_id: str
    picker_uri: str
    media_items_set: bool
    expire_time: str | None = None
    poll_interval_seconds: float = 3.0


@dataclass(frozen=True)
class PickedVideoItem:
    """Vom Nutzer im Google Photos Picker ausgewähltes Video."""

    media_id: str
    filename: str
    mime_type: str
    base_url: str
    create_time: str | None = None
    fps: float | None = None
    processing_status: str = "READY"


@dataclass(frozen=True)
class DriveVideoFile:
    """Video-Datei im Google Drive Staging-Ordner."""

    drive_file_id: str
    filename: str
    mime_type: str
    size_bytes: int
    created_time: str | None = None
    modified_time: str | None = None
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    photos_media_id: str | None = None
    original_created_at: str | None = None
    trashed: bool = False


@dataclass(frozen=True)
class VideoQueueItem:
    """Persistierter Queue-Eintrag eines gestagten Videos in SQLite/Turso."""

    id: str
    drive_file_id: str
    filename: str
    mime_type: str = "video/mp4"
    photos_media_id: str | None = None
    content_sha256: str | None = None
    size_bytes: int = 0
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    fps: float | None = None
    orientation: str | None = None
    recorded_at: str | None = None
    imported_at: str = ""
    status: VideoQueueStatus = VideoQueueStatus.QUEUED
    matched_profile: str | None = None
    youtube_video_id: str | None = None
    youtube_url: str | None = None
    title_override: str | None = None
    description_override: str | None = None
    hashtags_override: tuple[str, ...] = ()
    generated_title: str | None = None
    generated_description: str | None = None
    generated_hashtags: tuple[str, ...] = ()
    drive_trashed: bool = False
    error_message: str | None = None
    uploaded_at: str | None = None
    updated_at: str = ""


@dataclass(frozen=True)
class FilterEvaluation:
    """Ergebnis der Profilprüfung eines Videos inklusive verständlicher Ausschlussgründe."""

    matched: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class UploadResult:
    """Ergebnis eines erfolgreichen YouTube Data API v3 Uploads."""

    video_id: str
    youtube_url: str
    title: str
    description: str
    tags: tuple[str, ...]
    privacy_status: PrivacyStatus


@dataclass(frozen=True)
class UploadRunRecord:
    """Protokolleintrag eines Bot-Durchlaufs."""

    run_id: str
    started_at: str
    finished_at: str | None = None
    trigger_source: TriggerSource = TriggerSource.CLI
    profile_name: str = ""
    dry_run: bool = False
    status: RunStatus = RunStatus.SUCCESS
    scanned_count: int = 0
    eligible_count: int = 0
    uploaded_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    uploaded_video_ids: tuple[str, ...] = field(default_factory=tuple)
    summary_message: str = ""
