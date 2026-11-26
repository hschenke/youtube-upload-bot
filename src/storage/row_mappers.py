"""Typisierte Mapper zwischen SQL-Ergebniszeilen und Domänen-Dataclasses."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from src.domain.enums import (
    PrivacyStatus,
    RunStatus,
    SelectionOrder,
    TriggerSource,
    VideoOrientation,
    VideoQueueStatus,
)
from src.domain.models import UploadProfile, UploadRunRecord, VideoQueueItem


def _parse_json_tuple(raw: Any) -> tuple[str, ...]:
    if not raw:
        return ()
    if isinstance(raw, list | tuple):
        return tuple(str(item) for item in raw)
    try:
        loaded = json.loads(str(raw))
        if isinstance(loaded, list):
            return tuple(str(item) for item in loaded)
    except (ValueError, TypeError):
        return ()
    return ()


def _opt_float(value: Any) -> float | None:
    return float(value) if value is not None else None


def _opt_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def row_to_upload_profile(row: Mapping[str, Any]) -> UploadProfile:
    """Konvertiert eine Zeile aus `upload_profiles` in `UploadProfile`."""
    return UploadProfile(
        name=str(row["name"]),
        display_name=str(row["display_name"]),
        enabled=bool(int(row.get("enabled", 1))),
        orientation=VideoOrientation(str(row.get("orientation") or "portrait")),
        min_aspect_ratio=_opt_float(row.get("min_aspect_ratio")),
        max_aspect_ratio=_opt_float(row.get("max_aspect_ratio")),
        min_duration_seconds=_opt_float(row.get("min_duration_seconds")),
        max_duration_seconds=_opt_float(row.get("max_duration_seconds")),
        min_width=_opt_int(row.get("min_width")),
        min_height=_opt_int(row.get("min_height")),
        date_from=str(row["date_from"]) if row.get("date_from") else None,
        date_to=str(row["date_to"]) if row.get("date_to") else None,
        include_filename_patterns=_parse_json_tuple(row.get("include_filename_patterns_json")),
        exclude_filename_patterns=_parse_json_tuple(row.get("exclude_filename_patterns_json")),
        selection_order=SelectionOrder(str(row.get("selection_order") or "oldest_first")),
        max_uploads_per_run=int(row.get("max_uploads_per_run") or 1),
        privacy_status=PrivacyStatus(str(row.get("privacy_status") or "public")),
        category_id=str(row.get("category_id") or "22"),
        made_for_kids=bool(int(row.get("made_for_kids", 0))),
        language=str(row.get("language") or "en"),
        required_hashtags=_parse_json_tuple(row.get("required_hashtags_json")),
        default_tags=_parse_json_tuple(row.get("default_tags_json")),
        description_footer=str(row.get("description_footer") or ""),
        ai_prompt=str(row.get("ai_prompt") or ""),
        updated_at=str(row.get("updated_at") or ""),
    )


def row_to_video_queue_item(row: Mapping[str, Any]) -> VideoQueueItem:
    """Konvertiert eine Zeile aus `video_queue` in `VideoQueueItem`."""
    return VideoQueueItem(
        id=str(row["id"]),
        drive_file_id=str(row["drive_file_id"]),
        filename=str(row["filename"]),
        mime_type=str(row.get("mime_type") or "video/mp4"),
        photos_media_id=str(row["photos_media_id"]) if row.get("photos_media_id") else None,
        content_sha256=str(row["content_sha256"]) if row.get("content_sha256") else None,
        size_bytes=int(row.get("size_bytes") or 0),
        width=_opt_int(row.get("width")),
        height=_opt_int(row.get("height")),
        duration_seconds=_opt_float(row.get("duration_seconds")),
        fps=_opt_float(row.get("fps")),
        orientation=str(row["orientation"]) if row.get("orientation") else None,
        recorded_at=str(row["recorded_at"]) if row.get("recorded_at") else None,
        imported_at=str(row.get("imported_at") or ""),
        status=VideoQueueStatus(str(row.get("status") or "queued")),
        matched_profile=str(row["matched_profile"]) if row.get("matched_profile") else None,
        youtube_video_id=str(row["youtube_video_id"]) if row.get("youtube_video_id") else None,
        youtube_url=str(row["youtube_url"]) if row.get("youtube_url") else None,
        title_override=str(row["title_override"]) if row.get("title_override") else None,
        description_override=(
            str(row["description_override"]) if row.get("description_override") else None
        ),
        hashtags_override=_parse_json_tuple(row.get("hashtags_override_json")),
        generated_title=str(row["generated_title"]) if row.get("generated_title") else None,
        generated_description=(
            str(row["generated_description"]) if row.get("generated_description") else None
        ),
        generated_hashtags=_parse_json_tuple(row.get("generated_hashtags_json")),
        drive_trashed=bool(int(row.get("drive_trashed", 0))),
        error_message=str(row["error_message"]) if row.get("error_message") else None,
        uploaded_at=str(row["uploaded_at"]) if row.get("uploaded_at") else None,
        updated_at=str(row.get("updated_at") or ""),
    )


def row_to_upload_run(row: Mapping[str, Any]) -> UploadRunRecord:
    """Konvertiert eine Zeile aus `upload_runs` in `UploadRunRecord`."""
    return UploadRunRecord(
        run_id=str(row["run_id"]),
        started_at=str(row["started_at"]),
        finished_at=str(row["finished_at"]) if row.get("finished_at") else None,
        trigger_source=TriggerSource(str(row.get("trigger_source") or "cli")),
        profile_name=str(row.get("profile_name") or ""),
        dry_run=bool(int(row.get("dry_run", 0))),
        status=RunStatus(str(row.get("status") or "success")),
        scanned_count=int(row.get("scanned_count") or 0),
        eligible_count=int(row.get("eligible_count") or 0),
        uploaded_count=int(row.get("uploaded_count") or 0),
        skipped_count=int(row.get("skipped_count") or 0),
        failed_count=int(row.get("failed_count") or 0),
        uploaded_video_ids=_parse_json_tuple(row.get("uploaded_video_ids_json")),
        summary_message=str(row.get("summary_message") or ""),
    )
