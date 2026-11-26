"""Tests für SQLite/Turso-Persistenz, Profile-Seeding und Dreifach-Duplikatschutz."""

from __future__ import annotations

from pathlib import Path

import pytest
from src.config.settings import load_app_settings
from src.domain.enums import RunStatus, TriggerSource, VideoQueueStatus
from src.domain.models import DriveVideoFile, UploadRunRecord
from src.storage.repository import create_repository
from src.storage.turso_executor import TursoExecutor, normalize_turso_pipeline_url


def test_sqlite_repository_crud_and_triple_duplicate_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "test_bot.db"
    monkeypatch.setenv("LOCAL_DB_PATH", str(db_path))
    monkeypatch.delenv("TURSO_URL", raising=False)
    monkeypatch.delenv("TURSO_KEY", raising=False)

    settings = load_app_settings(yaml_path=Path("config/settings.yaml"), dotenv_path=None)
    repo = create_repository(settings)
    try:
        profiles = repo.list_profiles()
        assert {p.name for p in profiles} >= {"shorts", "landscape"}

        drive_file = DriveVideoFile(
            drive_file_id="drv_1",
            filename="clip_1.mp4",
            mime_type="video/mp4",
            size_bytes=123456,
            width=1080,
            height=1920,
            duration_seconds=18.5,
            photos_media_id="pho_1",
            original_created_at="2026-10-01T12:00:00Z",
        )
        queued = repo.upsert_staged_video(drive_file, content_sha256="sha_abc")
        assert queued.orientation == "portrait"
        assert not repo.is_already_uploaded(drive_file_id="drv_1")

        assert repo.claim_video_for_upload(queued.id, "shorts")
        assert not repo.claim_video_for_upload(queued.id, "shorts")

        repo.mark_video_uploaded(
            queued.id,
            profile_name="shorts",
            youtube_video_id="yt_999",
            youtube_url="https://youtube.com/shorts/yt_999",
            generated_title="Awesome Clip",
            generated_description="Desc #Shorts",
            generated_hashtags=["#Shorts"],
            drive_trashed=True,
        )

        assert repo.is_already_uploaded(drive_file_id="drv_1")
        assert repo.is_already_uploaded(photos_media_id="pho_1")
        assert repo.is_already_uploaded(content_sha256="sha_abc")

        uploaded = repo.list_videos(status=VideoQueueStatus.UPLOADED)
        assert len(uploaded) == 1
        assert uploaded[0].drive_trashed is True

        run = UploadRunRecord(
            run_id="run_1",
            started_at="2026-11-26T16:25:00+00:00",
            finished_at="2026-11-26T16:26:00+00:00",
            trigger_source=TriggerSource.GITHUB_ACTIONS,
            profile_name="shorts",
            status=RunStatus.SUCCESS,
            scanned_count=1,
            eligible_count=1,
            uploaded_count=1,
            uploaded_video_ids=("yt_999",),
            summary_message="OK",
        )
        repo.record_upload_run(run)
        runs = repo.list_upload_runs()
        assert len(runs) == 1
        assert runs[0].uploaded_video_ids == ("yt_999",)
    finally:
        repo.close()


def test_turso_executor_http_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    assert normalize_turso_pipeline_url("libsql://my-db.turso.io") == "https://my-db.turso.io/v2/pipeline"

    class FakeResp:
        status_code = 200

        @staticmethod
        def json() -> dict:
            return {
                "results": [
                    {
                        "type": "ok",
                        "response": {
                            "type": "execute",
                            "result": {
                                "cols": [{"name": "cnt"}],
                                "rows": [[{"type": "integer", "value": "3"}]],
                                "affected_row_count": 0,
                            },
                        },
                    }
                ]
            }

    executor = TursoExecutor("libsql://my-db.turso.io", "secret-token")
    monkeypatch.setattr(executor._session, "post", lambda *args, **kwargs: FakeResp())
    res = executor.execute("SELECT COUNT(*) AS cnt FROM video_queue")
    assert res.rows == [{"cnt": 3}]
    executor.close()
