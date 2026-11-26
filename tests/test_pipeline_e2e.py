"""End-to-End Pipeline-Tests (Sync, Probe, Duplikatschutz, Dry-Run, Live-Upload & Trash)."""

from __future__ import annotations

from pathlib import Path

from src.config.settings import load_app_settings
from src.domain.enums import PrivacyStatus, RunStatus, TriggerSource, VideoQueueStatus
from src.domain.models import (
    DriveVideoFile,
    MediaProbeResult,
    PickedVideoItem,
    PickerSessionInfo,
    UploadProfile,
    UploadResult,
    VideoQueueItem,
)
from src.domain.schemas import GeneratedVideoMetadata
from src.storage.repository import create_repository
from src.worker.pipeline import UploadPipelineService


class _FakePicker:
    def __init__(self, items: list[PickedVideoItem]) -> None:
        self._items = items
        self.deleted_sessions: list[str] = []

    def get_session(self, session_id: str) -> PickerSessionInfo:
        return PickerSessionInfo(session_id=session_id, picker_uri="https://photos.google.com/p", media_items_set=True)

    def list_video_items(self, session_id: str) -> list[PickedVideoItem]:
        return list(self._items)

    def download_video_to_path(self, item: PickedVideoItem, target_dir: Path) -> Path:
        p = target_dir / item.filename
        p.write_bytes(b"video-content-" + item.media_id.encode("utf-8"))
        return p

    def delete_session(self, session_id: str) -> None:
        self.deleted_sessions.append(session_id)


class _FakeDrive:
    def __init__(self, files: list[DriveVideoFile]) -> None:
        self._files = files
        self.trashed: list[str] = []
        self.uploaded_to_drive: list[str] = []

    def ensure_staging_folder(self) -> str:
        return "staging_folder_1"

    def list_staged_videos(self, folder_id: str | None = None) -> list[DriveVideoFile]:
        return [f for f in self._files if f.drive_file_id not in self.trashed]

    def upload_video_file(self, local_path: Path, **kwargs: object) -> DriveVideoFile:
        self.uploaded_to_drive.append(str(kwargs["filename"]))
        df = DriveVideoFile(
            drive_file_id=f"drv_{len(self._files) + 1}",
            filename=str(kwargs["filename"]),
            mime_type=str(kwargs.get("mime_type") or "video/mp4"),
            size_bytes=local_path.stat().st_size,
            width=1080,
            height=1920,
            duration_seconds=22.0,
            photos_media_id=str(kwargs.get("photos_media_id") or ""),
            original_created_at=str(kwargs.get("original_created_at") or ""),
        )
        self._files.append(df)
        return df

    def download_video_to_path(self, drive_file_id: str, filename: str, target_dir: Path) -> Path:
        p = target_dir / filename
        p.write_bytes(b"video-bytes-" + drive_file_id.encode("utf-8"))
        return p

    def trash_file(self, drive_file_id: str) -> None:
        self.trashed.append(drive_file_id)


class _FakeYouTube:
    def __init__(self) -> None:
        self.uploads: list[str] = []

    def upload_video(self, local_path: Path, *, metadata: GeneratedVideoMetadata, privacy_status: PrivacyStatus, **kwargs: object) -> UploadResult:
        vid_id = f"yt_{len(self.uploads) + 1}"
        self.uploads.append(vid_id)
        return UploadResult(
            video_id=vid_id,
            youtube_url=f"https://youtube.com/shorts/{vid_id}",
            title=metadata.title,
            description=metadata.description,
            tags=tuple(metadata.tags),
            privacy_status=privacy_status,
        )


class _FakeAI:
    def generate(self, video_path: Path, video: VideoQueueItem, profile: UploadProfile) -> GeneratedVideoMetadata:
        return GeneratedVideoMetadata(
            title=f"AI Title for {video.filename}",
            description="Generated AI description #Shorts",
            hashtags=["#Shorts", "#Travel"],
            tags=["shorts", "travel"],
        )


class _FakeNotifier:
    def __init__(self) -> None:
        self.success_calls: int = 0
        self.empty_calls: int = 0
        self.error_calls: int = 0

    def send_upload_success(self, result: UploadResult, **kwargs: object) -> bool:
        self.success_calls += 1
        return True

    def send_empty_queue_notice(self, profile_name: str) -> bool:
        self.empty_calls += 1
        return True

    def send_error_notice(self, run: object, error_summary: str) -> bool:
        self.error_calls += 1
        return True


def _fake_probe(video_path: Path) -> MediaProbeResult:
    if "landscape" in video_path.name:
        return MediaProbeResult(1920, 1080, 1920, 1080, 0, 30.0, 30.0, "h264", True)
    return MediaProbeResult(1920, 1080, 1080, 1920, 90, 25.0, 30.0, "h264", True, "2026-07-15T10:00:00Z")


def test_full_pipeline_ingest_dry_run_live_upload_and_empty_queue(tmp_path: Path, monkeypatch: object) -> None:
    monkeypatch.setenv("LOCAL_DB_PATH", str(tmp_path / "e2e.db"))  # type: ignore[attr-defined]
    monkeypatch.delenv("TURSO_URL", raising=False)  # type: ignore[attr-defined]
    settings = load_app_settings(yaml_path=Path("config/settings.yaml"), dotenv_path=None)
    repo = create_repository(settings)

    try:
        picker = _FakePicker(
            [
                PickedVideoItem("pho_1", "short_1.mp4", "video/mp4", "https://lh3.googleusercontent.com/1", "2026-07-15T10:00:00Z"),
            ]
        )
        drive = _FakeDrive(
            [
                DriveVideoFile(
                    drive_file_id="drv_landscape",
                    filename="landscape_clip.mp4",
                    mime_type="video/mp4",
                    size_bytes=5000,
                    width=1920,
                    height=1080,
                    duration_seconds=30.0,
                )
            ]
        )
        yt = _FakeYouTube()
        notifier = _FakeNotifier()

        service = UploadPipelineService(
            settings,
            repo,
            picker_client=picker,  # type: ignore[arg-type]
            drive_client=drive,  # type: ignore[arg-type]
            youtube_client=yt,  # type: ignore[arg-type]
            metadata_generator=_FakeAI(),
            notifier=notifier,  # type: ignore[arg-type]
            probe_fn=_fake_probe,
        )

        # 1. Picker Ingest
        summary = service.import_from_picker_session("sess_99")
        assert summary.imported_count == 1
        assert picker.deleted_sessions == ["sess_99"]

        # 2. Dry-Run (darf weder YouTube noch Drive-Papierkorb auslösen)
        dry_run = service.run_scheduled_upload(profile_name="shorts", dry_run=True)
        assert dry_run.status == RunStatus.SUCCESS
        assert dry_run.uploaded_count == 1
        assert yt.uploads == []
        assert drive.trashed == []

        # 3. Live-Run (lädt nur das Portrait-Short hoch, lässt Landscape unberührt, verschiebt Short in Drive-Papierkorb)
        live_run = service.run_scheduled_upload(
            profile_name="shorts",
            dry_run=False,
            trigger_source=TriggerSource.GITHUB_ACTIONS,
        )
        assert live_run.status == RunStatus.SUCCESS
        assert live_run.uploaded_count == 1
        assert yt.uploads == ["yt_1"]
        assert len(drive.trashed) == 1
        assert notifier.success_calls == 1

        # Landscape bleibt in Queue; Short ist uploaded + drive_trashed
        queued = repo.list_videos(status=VideoQueueStatus.QUEUED)
        assert [v.filename for v in queued] == ["landscape_clip.mp4"]

        # 4. Nächster Run für 'shorts' → Queue leer → Benachrichtigung
        empty_run = service.run_scheduled_upload(profile_name="shorts", dry_run=False)
        assert empty_run.status == RunStatus.EMPTY
        assert notifier.empty_calls == 1
    finally:
        repo.close()
