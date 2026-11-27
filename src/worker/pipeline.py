"""End-to-End Pipeline-Orchestrierung: Picker Ingest, Drive Sync, Probe, AI, YouTube & Trash."""

from __future__ import annotations

import logging
import secrets
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from src.ai.metadata_generator import (
    GeminiVideoMetadataGenerator,
    TemplateVideoMetadataGenerator,
    VideoMetadataGenerator,
    compose_final_metadata,
)
from src.config.settings import AppSettings
from src.domain.enums import (
    PrivacyStatus,
    RunStatus,
    TriggerSource,
    VideoOrientation,
    VideoQueueStatus,
)
from src.domain.exceptions import BotError
from src.domain.models import (
    MediaProbeResult,
    UploadProfile,
    UploadResult,
    UploadRunRecord,
    VideoQueueItem,
)
from src.domain.schemas import GeneratedVideoMetadata
from src.integrations.drive_staging import GoogleDriveStagingClient
from src.integrations.photos_picker import GooglePhotosPickerClient
from src.integrations.youtube_uploader import YouTubeUploaderClient
from src.media.filter_engine import evaluate_video_for_profile, select_candidates
from src.media.probe import compute_file_sha256, probe_video_file
from src.notifications.email_channel import EmailNotificationChannel
from src.security.google_oauth import GoogleOAuthCredentialProvider
from src.storage.repository import SqlBotRepository, utc_now_iso

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImportSummary:
    """Ergebnis eines Google-Photos-Picker-Imports in den Drive-Staging-Ordner."""

    picked_videos: int
    imported_count: int
    skipped_duplicates: int
    failed_count: int


@dataclass
class _RunCounters:
    scanned: int = 0
    eligible: int = 0
    uploaded: int = 0
    skipped: int = 0
    failed: int = 0
    uploaded_video_ids: list[str] | None = None
    errors: list[str] | None = None

    def __post_init__(self) -> None:
        if self.uploaded_video_ids is None:
            self.uploaded_video_ids = []
        if self.errors is None:
            self.errors = []


class UploadPipelineService:
    """Koordiniert Ingest, Drive-Sync, Profilfilterung, KI-Metadaten, Upload und Cleanup."""

    def __init__(
        self,
        settings: AppSettings,
        repository: SqlBotRepository,
        *,
        picker_client: GooglePhotosPickerClient | None = None,
        drive_client: GoogleDriveStagingClient | None = None,
        youtube_client: YouTubeUploaderClient | None = None,
        metadata_generator: VideoMetadataGenerator | None = None,
        notifier: EmailNotificationChannel | None = None,
        probe_fn: Callable[[Path], MediaProbeResult] = probe_video_file,
    ) -> None:
        self._settings = settings
        self._repo = repository
        creds = GoogleOAuthCredentialProvider(settings, repository=repository)
        self._picker = picker_client or GooglePhotosPickerClient(creds)
        self._drive = drive_client or GoogleDriveStagingClient(
            creds,
            folder_id=settings.drive_staging_folder_id,
            folder_name=settings.drive_staging_folder_name,
        )
        self._youtube = youtube_client or YouTubeUploaderClient(creds)
        self._metadata_gen = metadata_generator or self._build_metadata_generator(settings)
        self._fallback_gen = TemplateVideoMetadataGenerator()
        self._notifier = notifier or EmailNotificationChannel(settings)
        self._probe_fn = probe_fn

    @staticmethod
    def _build_metadata_generator(settings: AppSettings) -> VideoMetadataGenerator:
        if settings.has_gemini_configured:
            return GeminiVideoMetadataGenerator(settings)
        return TemplateVideoMetadataGenerator()

    def import_from_picker_session(self, session_id: str) -> ImportSummary:
        """Streamt gewählte Picker-Videos per Temp-Datei nach Drive und persistiert Metadaten."""
        items = self._picker.list_video_items(session_id)
        if not items:
            self._picker.delete_session(session_id)
            return ImportSummary(0, 0, 0, 0)

        folder_id = self._drive.ensure_staging_folder()
        imported = 0
        skipped = 0
        failed = 0

        for item in items:
            if self._repo.is_already_uploaded(photos_media_id=item.media_id):
                skipped += 1
                continue
            try:
                with tempfile.TemporaryDirectory(prefix="ytbot_ingest_") as tmp_dir:
                    local_path = self._picker.download_video_to_path(item, Path(tmp_dir))
                    sha256_hex = compute_file_sha256(local_path)
                    if self._repo.is_already_uploaded(content_sha256=sha256_hex):
                        skipped += 1
                        continue
                    probe_res = self._try_probe(local_path)
                    drive_file = self._drive.upload_video_file(
                        local_path,
                        filename=item.filename,
                        mime_type=item.mime_type,
                        folder_id=folder_id,
                        photos_media_id=item.media_id,
                        original_created_at=item.create_time or (probe_res.creation_time if probe_res else None),
                    )
                    self._repo.upsert_staged_video(
                        drive_file,
                        width=probe_res.display_width if probe_res else None,
                        height=probe_res.display_height if probe_res else None,
                        duration_seconds=probe_res.duration_seconds if probe_res else None,
                        fps=probe_res.fps if probe_res else item.fps,
                        content_sha256=sha256_hex,
                    )
                    imported += 1
            except Exception as exc:
                failed += 1
                logger.exception("Import von Picker-Video '%s' fehlgeschlagen: %s", item.filename, exc)

        self._picker.delete_session(session_id)
        return ImportSummary(len(items), imported, skipped, failed)

    def sync_drive_queue(self) -> tuple[int, int]:
        """Synchronisiert alle Videos aus dem Drive-Staging-Ordner in die Queue-Tabelle."""
        staged_files = self._drive.list_staged_videos()
        active_ids: set[str] = set()
        for drive_file in staged_files:
            active_ids.add(drive_file.drive_file_id)
            self._repo.upsert_staged_video(drive_file)
        missing_skipped = self._repo.mark_missing_drive_videos_skipped(active_ids)
        return len(staged_files), missing_skipped

    def run_scheduled_upload(
        self,
        *,
        profile_name: str = "",
        dry_run: bool = False,
        privacy_override: PrivacyStatus | None = None,
        max_uploads_override: int | None = None,
        video_id: str = "",
        trigger_source: TriggerSource = TriggerSource.CLI,
    ) -> UploadRunRecord:
        """Führt den vollständigen Sync-, Filter-, Analyse- und Upload-Zyklus aus."""
        run_id = f"run_{secrets.token_hex(6)}"
        started_at = utc_now_iso()
        counters = _RunCounters()

        try:
            scanned, _ = self.sync_drive_queue()
            counters.scanned = scanned
            profiles = self._resolve_target_profiles(profile_name)
            all_queued = self._repo.list_videos(status=VideoQueueStatus.QUEUED, limit=1000)

            for profile in profiles:
                self._process_profile(
                    profile=profile,
                    queued_videos=all_queued,
                    dry_run=dry_run,
                    privacy_override=privacy_override,
                    max_uploads_override=max_uploads_override,
                    target_video_id=video_id.strip(),
                    counters=counters,
                )
                all_queued = self._repo.list_videos(status=VideoQueueStatus.QUEUED, limit=1000)
        except Exception as exc:
            logger.exception("Kritischer Pipeline-Fehler in Run '%s': %s", run_id, exc)
            counters.failed += 1
            if counters.errors is not None:
                counters.errors.append(str(exc))

        run_status = self._determine_run_status(counters)
        summary = self._build_run_summary(counters, dry_run=dry_run)
        run_record = UploadRunRecord(
            run_id=run_id,
            started_at=started_at,
            finished_at=utc_now_iso(),
            trigger_source=trigger_source,
            profile_name=profile_name or "active",
            dry_run=dry_run,
            status=run_status,
            scanned_count=counters.scanned,
            eligible_count=counters.eligible,
            uploaded_count=counters.uploaded,
            skipped_count=counters.skipped,
            failed_count=counters.failed,
            uploaded_video_ids=tuple(counters.uploaded_video_ids or ()),
            summary_message=summary,
        )
        self._repo.record_upload_run(run_record)
        self._send_run_notifications(run_record, counters.errors or [], profile_name=profile_name)
        return run_record

    def _resolve_target_profiles(self, profile_name: str) -> list[UploadProfile]:
        clean = profile_name.strip().lower()
        if clean:
            profile = self._repo.get_profile(clean)
            if profile is None:
                raise BotError(f"Upload-Profil '{clean}' nicht gefunden.")
            return [profile]
        profiles = self._repo.list_profiles(enabled_only=True)
        if not profiles:
            raise BotError("Keine aktiven Upload-Profile konfiguriert.")
        return profiles

    def _process_profile(
        self,
        *,
        profile: UploadProfile,
        queued_videos: list[VideoQueueItem],
        dry_run: bool,
        privacy_override: PrivacyStatus | None,
        max_uploads_override: int | None,
        target_video_id: str,
        counters: _RunCounters,
    ) -> None:
        candidates = select_candidates(queued_videos, profile)
        if target_video_id:
            candidates = [c for c in candidates if c.id == target_video_id]

        counters.eligible += len(candidates)
        upload_limit = (
            max_uploads_override
            if max_uploads_override and max_uploads_override > 0
            else max(1, profile.max_uploads_per_run)
        )
        uploaded_for_profile = 0

        for candidate in candidates:
            if uploaded_for_profile >= upload_limit:
                break
            outcome = self._process_single_candidate(
                candidate=candidate,
                profile=profile,
                dry_run=dry_run,
                privacy_override=privacy_override,
                counters=counters,
            )
            if outcome == "uploaded":
                uploaded_for_profile += 1

    def _process_single_candidate(
        self,
        *,
        candidate: VideoQueueItem,
        profile: UploadProfile,
        dry_run: bool,
        privacy_override: PrivacyStatus | None,
        counters: _RunCounters,
    ) -> str:
        with tempfile.TemporaryDirectory(prefix="ytbot_run_") as tmp_dir:
            try:
                local_path = self._drive.download_video_to_path(
                    candidate.drive_file_id,
                    candidate.filename,
                    Path(tmp_dir),
                )
                sha256_hex = compute_file_sha256(local_path)
                probe_res = self._probe_fn(local_path)
                self._repo.update_probe_metadata(
                    candidate.id,
                    width=probe_res.display_width,
                    height=probe_res.display_height,
                    duration_seconds=probe_res.duration_seconds,
                    fps=probe_res.fps,
                    content_sha256=sha256_hex,
                    recorded_at=probe_res.creation_time,
                )
                refreshed = self._repo.get_video_by_id(candidate.id) or candidate
                evaluation = evaluate_video_for_profile(refreshed, profile)
                if not evaluation.matched:
                    logger.info(
                        "Video '%s' nach exaktem ffprobe für '%s' ausgeschlossen: %s",
                        refreshed.filename,
                        profile.name,
                        "; ".join(evaluation.reasons),
                    )
                    counters.skipped += 1
                    return "skipped"

                if self._repo.is_already_uploaded(
                    drive_file_id=refreshed.drive_file_id,
                    photos_media_id=refreshed.photos_media_id,
                    content_sha256=sha256_hex,
                ):
                    self._repo.update_video_status(
                        refreshed.id,
                        VideoQueueStatus.SKIPPED,
                        error_message="Duplikat: identischer Video-Hash bereits hochgeladen.",
                    )
                    counters.skipped += 1
                    return "skipped"

                metadata = self._generate_metadata(local_path, refreshed, profile)
                if dry_run:
                    logger.info(
                        "[DRY-RUN] Würde '%s' als '%s' hochladen.",
                        refreshed.filename,
                        metadata.title,
                    )
                    counters.uploaded += 1
                    if counters.uploaded_video_ids is not None:
                        counters.uploaded_video_ids.append(f"dry:{refreshed.id}")
                    return "uploaded"

                if not self._repo.claim_video_for_upload(refreshed.id, profile.name):
                    counters.skipped += 1
                    return "skipped"

                privacy = privacy_override or profile.privacy_status
                is_short = profile.orientation == VideoOrientation.PORTRAIT
                upload_res = self._youtube.upload_video(
                    local_path,
                    metadata=metadata,
                    privacy_status=privacy,
                    category_id=profile.category_id,
                    made_for_kids=profile.made_for_kids,
                    is_short=is_short,
                )
                drive_trashed = self._trash_drive_copy_safely(refreshed.drive_file_id)
                self._repo.mark_video_uploaded(
                    refreshed.id,
                    profile_name=profile.name,
                    youtube_video_id=upload_res.video_id,
                    youtube_url=upload_res.youtube_url,
                    generated_title=upload_res.title,
                    generated_description=upload_res.description,
                    generated_hashtags=metadata.hashtags,
                    drive_trashed=drive_trashed,
                )
                counters.uploaded += 1
                if counters.uploaded_video_ids is not None:
                    counters.uploaded_video_ids.append(upload_res.video_id)
                self._notify_single_upload(upload_res, profile_name=profile.name)
                return "uploaded"
            except Exception as exc:
                counters.failed += 1
                if counters.errors is not None:
                    counters.errors.append(f"{candidate.filename}: {exc}")
                self._repo.update_video_status(
                    candidate.id,
                    VideoQueueStatus.FAILED,
                    error_message=str(exc)[:400],
                )
                logger.exception("Verarbeitung von '%s' fehlgeschlagen: %s", candidate.filename, exc)
                return "failed"

    def _generate_metadata(
        self,
        local_path: Path,
        video: VideoQueueItem,
        profile: UploadProfile,
    ) -> GeneratedVideoMetadata:
        if video.title_override and video.description_override:
            manual = GeneratedVideoMetadata(
                title=video.title_override,
                description=video.description_override,
                hashtags=list(video.hashtags_override),
                tags=list(profile.default_tags),
            )
            return compose_final_metadata(manual, profile, video)
        try:
            return self._metadata_gen.generate(local_path, video, profile)
        except Exception as exc:
            logger.warning(
                "KI-Metadaten fehlgeschlagen für '%s' – nutze Template-Fallback: %s",
                video.filename,
                exc,
            )
            return self._fallback_gen.generate(local_path, video, profile)

    def _trash_drive_copy_safely(self, drive_file_id: str) -> bool:
        try:
            self._drive.trash_file(drive_file_id)
            return True
        except Exception as exc:
            logger.warning(
                "YouTube-Upload war erfolgreich, Drive-Papierkorb für '%s' fehlgeschlagen: %s",
                drive_file_id,
                exc,
            )
            return False

    def _try_probe(self, video_path: Path) -> MediaProbeResult | None:
        try:
            return self._probe_fn(video_path)
        except Exception as exc:
            logger.warning("ffprobe beim Ingest übersprungen (%s): %s", video_path.name, exc)
            return None

    def _notify_single_upload(self, result: UploadResult, *, profile_name: str) -> None:
        remaining = len(self._repo.list_videos(status=VideoQueueStatus.QUEUED, limit=1000))
        self._notifier.send_upload_success(
            result,
            profile_name=profile_name,
            remaining_in_queue=remaining,
        )

    def _send_run_notifications(
        self,
        run_record: UploadRunRecord,
        errors: list[str],
        *,
        profile_name: str,
    ) -> None:
        if run_record.dry_run:
            return
        if run_record.status == RunStatus.EMPTY:
            self._notifier.send_empty_queue_notice(profile_name)
        elif run_record.failed_count > 0 and errors:
            self._notifier.send_error_notice(run_record, "\n".join(errors))

    @staticmethod
    def _determine_run_status(counters: _RunCounters) -> RunStatus:
        if counters.failed > 0 and counters.uploaded > 0:
            return RunStatus.PARTIAL
        if counters.failed > 0 and counters.uploaded == 0:
            return RunStatus.FAILED
        if counters.eligible == 0 and counters.uploaded == 0:
            return RunStatus.EMPTY
        return RunStatus.SUCCESS

    @staticmethod
    def _build_run_summary(counters: _RunCounters, *, dry_run: bool) -> str:
        prefix = "[DRY-RUN] " if dry_run else ""
        return (
            f"{prefix}Gescannt: {counters.scanned}, Passend: {counters.eligible}, "
            f"Hochgeladen: {counters.uploaded}, Übersprungen: {counters.skipped}, "
            f"Fehler: {counters.failed}."
        )
