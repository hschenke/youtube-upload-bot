"""Tests für Photos Picker, Drive Staging, YouTube Uploader, Gemini AI & Notifications."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from src.ai.metadata_generator import (
    GeminiVideoMetadataGenerator,
    TemplateVideoMetadataGenerator,
    compose_final_metadata,
)
from src.config.settings import AppSettings
from src.domain.enums import PrivacyStatus, VideoOrientation
from src.domain.exceptions import InputValidationError
from src.domain.models import PickedVideoItem, UploadProfile, UploadResult, VideoQueueItem
from src.domain.schemas import GeneratedVideoMetadata
from src.integrations.drive_staging import GoogleDriveStagingClient
from src.integrations.photos_picker import GooglePhotosPickerClient
from src.integrations.youtube_uploader import YouTubeUploaderClient
from src.notifications.email_channel import EmailNotificationChannel


class _FakeCreds:
    def get_access_token(self) -> str:
        return "fake-access-token"

    def get_credentials(self) -> object:
        return object()


def test_photos_picker_session_pagination_and_download(tmp_path: Path) -> None:
    calls: list[str] = []

    class FakeSession(requests.Session):
        def post(self, url: str, **kwargs: object) -> object:
            calls.append(f"POST {url}")
            return SimpleNamespace(
                status_code=200,
                json=lambda: {
                    "id": "sess_1",
                    "pickerUri": "https://photos.google.com/picker/sess_1",
                    "mediaItemsSet": False,
                    "pollingConfig": {"pollInterval": "5s"},
                },
            )

        def get(self, url: str, **kwargs: object) -> object:
            calls.append(f"GET {url}")
            if url.endswith("/mediaItems"):
                params = kwargs.get("params") or {}
                if not params.get("pageToken"):
                    return SimpleNamespace(
                        status_code=200,
                        json=lambda: {
                            "mediaItems": [
                                {"id": "p1", "type": "PHOTO", "mediaFile": {"baseUrl": "https://lh3.googleusercontent.com/p1"}},
                                {
                                    "id": "v1",
                                    "type": "VIDEO",
                                    "createTime": "2026-09-01T10:00:00Z",
                                    "mediaFile": {
                                        "baseUrl": "https://lh3.googleusercontent.com/v1",
                                        "mimeType": "video/mp4",
                                        "filename": "clip.mp4",
                                        "mediaFileMetadata": {"videoMetadata": {"fps": 60}},
                                    },
                                },
                            ],
                            "nextPageToken": "page2",
                        },
                    )
                return SimpleNamespace(status_code=200, json=lambda: {"mediaItems": []})

            return SimpleNamespace(
                status_code=200,
                iter_content=lambda chunk_size=1024: [b"video-bytes"],
                __enter__=lambda self=None: self,
                __exit__=lambda *a: None,
            )

    picker = GooglePhotosPickerClient(_FakeCreds(), session=FakeSession())  # type: ignore[arg-type]
    sess = picker.create_session(max_item_count=10)
    assert sess.session_id == "sess_1"
    assert sess.poll_interval_seconds == 5.0

    items = picker.list_video_items("sess_1")
    assert len(items) == 1
    assert items[0].media_id == "v1"
    assert items[0].fps == 60.0

    bad_item = PickedVideoItem(
        media_id="bad",
        filename="evil.mp4",
        mime_type="video/mp4",
        base_url="https://evil.example.com/v1",
    )
    with pytest.raises(InputValidationError):
        picker.download_video_to_path(bad_item, tmp_path)


def test_drive_staging_list_and_trash() -> None:
    trashed_ids: list[str] = []

    class FakeFilesResource:
        def list(self, **kwargs: object) -> object:
            return SimpleNamespace(
                execute=lambda: {
                    "files": [
                        {
                            "id": "drv_9",
                            "name": "short.mp4",
                            "mimeType": "video/mp4",
                            "size": "42000",
                            "createdTime": "2026-10-10T10:00:00Z",
                            "videoMediaMetadata": {"width": 1080, "height": 1920, "durationMillis": "15000"},
                            "appProperties": {"photos_media_id": "pho_9"},
                        }
                    ]
                }
            )

        def update(self, fileId: str, body: dict, fields: str) -> object:  # noqa: N803
            trashed_ids.append(fileId)
            return SimpleNamespace(execute=lambda: {"id": fileId, "trashed": body["trashed"]})

    fake_service = SimpleNamespace(files=lambda: FakeFilesResource())
    drive = GoogleDriveStagingClient(_FakeCreds(), folder_id="folder_1", service=fake_service)  # type: ignore[arg-type]
    videos = drive.list_staged_videos()
    assert len(videos) == 1
    assert videos[0].duration_seconds == 15.0
    assert videos[0].photos_media_id == "pho_9"

    drive.trash_file("drv_9")
    assert trashed_ids == ["drv_9"]


def test_youtube_uploader_resumable_insert(tmp_path: Path) -> None:
    video_file = tmp_path / "short.mp4"
    video_file.write_bytes(b"0000")

    captured_body: dict = {}

    class FakeInsertReq:
        def next_chunk(self) -> tuple[object, dict]:
            return None, {"id": "yt_abc123"}

    class FakeVideosResource:
        def insert(self, part: str, body: dict, media_body: object) -> FakeInsertReq:
            captured_body.update(body)
            return FakeInsertReq()

    fake_service = SimpleNamespace(videos=lambda: FakeVideosResource())
    uploader = YouTubeUploaderClient(_FakeCreds(), service=fake_service)  # type: ignore[arg-type]
    meta = GeneratedVideoMetadata(
        title="Morning Coffee <wow>",
        description="Fresh espresso pour #Shorts",
        hashtags=["#Shorts", "#Coffee"],
        tags=["shorts", "coffee"],
    )
    res = uploader.upload_video(video_file, metadata=meta, privacy_status=PrivacyStatus.PUBLIC, is_short=True)
    assert res.video_id == "yt_abc123"
    assert res.youtube_url == "https://youtube.com/shorts/yt_abc123"
    assert "<" not in captured_body["snippet"]["title"]
    assert captured_body["status"]["selfDeclaredMadeForKids"] is False


def test_gemini_generator_uploads_calls_interactions_and_deletes_in_finally(tmp_path: Path) -> None:
    video_file = tmp_path / "clip.mp4"
    video_file.write_bytes(b"fake-mp4")
    deleted_names: list[str] = []
    used_models: list[str] = []

    class FakeFiles:
        def upload(self, file: str, config: dict) -> object:
            return SimpleNamespace(name="files/temp123", uri="https://generativelanguage.googleapis.com/v1beta/files/temp123", state="ACTIVE", mime_type="video/mp4")

        def get(self, name: str) -> object:
            return SimpleNamespace(name=name, uri="https://generativelanguage.googleapis.com/v1beta/files/temp123", state="ACTIVE", mime_type="video/mp4")

        def delete(self, name: str) -> None:
            deleted_names.append(name)

    class FakeInteractions:
        def create(self, **kwargs: object) -> object:
            used_models.append(str(kwargs["model"]))
            payload = {
                "title": "Sunset Walk in Berlin",
                "description": "Evening light over the river.",
                "hashtags": ["#Berlin", "#Sunset"],
                "tags": ["berlin", "sunset"],
            }
            return SimpleNamespace(output_text=json.dumps(payload))

    fake_client = SimpleNamespace(files=FakeFiles(), interactions=FakeInteractions())
    settings = AppSettings(gemini_api_key="fake-key", gemini_model="gemini-3.8-flash")
    gen = GeminiVideoMetadataGenerator(settings, client=fake_client)  # type: ignore[arg-type]

    profile = UploadProfile(
        name="shorts",
        display_name="Shorts",
        orientation=VideoOrientation.PORTRAIT,
        required_hashtags=("#Shorts",),
        description_footer="Follow for daily clips!",
    )
    video = VideoQueueItem(id="v1", drive_file_id="d1", filename="IMG_1234.MP4")

    meta = gen.generate(video_file, video, profile)
    assert used_models == ["gemini-3.8-flash"]
    assert deleted_names == ["files/temp123"]
    assert "#Shorts" in meta.hashtags
    assert "Follow for daily clips!" in meta.description

    fallback = TemplateVideoMetadataGenerator().generate(video_file, video, profile)
    assert "#Shorts" in fallback.hashtags

    overridden = compose_final_metadata(
        meta,
        profile,
        VideoQueueItem(
            id="v2",
            drive_file_id="d2",
            filename="a.mp4",
            title_override="Manual Title",
            description_override="Manual Desc",
            hashtags_override=("#Custom",),
        ),
    )
    assert overridden.title == "Manual Title"
    assert "#Shorts" in overridden.hashtags
    assert "#Custom" in overridden.hashtags


def test_email_notifications_resend_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    sent_payloads: list[dict] = []

    def fake_post(url: str, headers: dict, json: dict, timeout: float) -> object:
        sent_payloads.append(json)
        return SimpleNamespace(status_code=201)

    monkeypatch.setattr("src.notifications.email_channel.requests.post", fake_post)
    settings = AppSettings(
        email_provider="resend",
        resend_api_key="re_test_key",
        email_to="holger@example.com",
        streamlit_app_url="https://ytbot.streamlit.app",
        app_password="pw",
    )
    channel = EmailNotificationChannel(settings)
    res = UploadResult(
        video_id="yt_1",
        youtube_url="https://youtube.com/shorts/yt_1",
        title="Nice <Clip>",
        description="Desc",
        tags=("shorts",),
        privacy_status=PrivacyStatus.PUBLIC,
    )
    assert channel.send_upload_success(res, profile_name="shorts", remaining_in_queue=4)
    assert len(sent_payloads) == 1
    assert "Nice &lt;Clip&gt;" in sent_payloads[0]["html"]
    assert "https://youtube.com/shorts/yt_1" in sent_payloads[0]["html"]
