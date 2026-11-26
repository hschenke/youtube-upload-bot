"""Tests für ffprobe-Rotationsauswertung und Profil-Filter-Engine."""

from __future__ import annotations

from src.domain.enums import SelectionOrder, VideoOrientation, VideoQueueStatus
from src.domain.models import UploadProfile, VideoQueueItem
from src.media.filter_engine import evaluate_video_for_profile, select_candidates
from src.media.probe import parse_ffprobe_payload


def test_parse_ffprobe_payload_handles_side_data_rotation() -> None:
    payload = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "30000/1001",
                "duration": "24.5",
                "side_data_list": [{"side_data_type": "Display Matrix", "rotation": -90}],
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {"duration": "24.5", "tags": {"creation_time": "2026-08-10T14:20:00Z"}},
    }
    res = parse_ffprobe_payload(payload, file_size_bytes=5_000_000)
    assert res.display_width == 1080
    assert res.display_height == 1920
    assert res.rotation_degrees == 270
    assert res.duration_seconds == 24.5
    assert res.has_audio is True
    assert res.creation_time == "2026-08-10T14:20:00Z"


def test_filter_engine_orientation_duration_dates_and_sorting() -> None:
    profile = UploadProfile(
        name="shorts",
        display_name="Shorts",
        orientation=VideoOrientation.PORTRAIT,
        min_aspect_ratio=0.45,
        max_aspect_ratio=0.85,
        min_duration_seconds=3.0,
        max_duration_seconds=180.0,
        min_width=360,
        min_height=640,
        date_from="2026-01-01",
        date_to="2026-12-31",
        exclude_filename_patterns=("*draft*",),
        selection_order=SelectionOrder.OLDEST_FIRST,
    )

    good_older = VideoQueueItem(
        id="v1",
        drive_file_id="d1",
        filename="trip_day1.mp4",
        width=1080,
        height=1920,
        duration_seconds=45.0,
        recorded_at="2026-05-01T10:00:00Z",
        status=VideoQueueStatus.QUEUED,
    )
    good_newer = VideoQueueItem(
        id="v2",
        drive_file_id="d2",
        filename="trip_day2.mp4",
        width=1080,
        height=1920,
        duration_seconds=120.0,
        recorded_at="2026-06-01T10:00:00Z",
        status=VideoQueueStatus.QUEUED,
    )
    landscape = VideoQueueItem(
        id="v3",
        drive_file_id="d3",
        filename="wide.mp4",
        width=1920,
        height=1080,
        duration_seconds=30.0,
        recorded_at="2026-04-01T10:00:00Z",
        status=VideoQueueStatus.QUEUED,
    )
    too_long = VideoQueueItem(
        id="v4",
        drive_file_id="d4",
        filename="long.mp4",
        width=1080,
        height=1920,
        duration_seconds=210.0,
        recorded_at="2026-04-01T10:00:00Z",
        status=VideoQueueStatus.QUEUED,
    )
    excluded_draft = VideoQueueItem(
        id="v5",
        drive_file_id="d5",
        filename="my_draft_clip.mp4",
        width=1080,
        height=1920,
        duration_seconds=20.0,
        recorded_at="2026-04-01T10:00:00Z",
        status=VideoQueueStatus.QUEUED,
    )

    assert not evaluate_video_for_profile(landscape, profile).matched
    assert not evaluate_video_for_profile(too_long, profile).matched
    assert not evaluate_video_for_profile(excluded_draft, profile).matched

    selected = select_candidates([good_newer, landscape, too_long, excluded_draft, good_older], profile)
    assert [v.id for v in selected] == ["v1", "v2"]
