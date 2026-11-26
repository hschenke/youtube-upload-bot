"""Regelbasierte Video-Filterung und Sortierung gemäß Upload-Profil."""

from __future__ import annotations

import fnmatch
import secrets
from collections.abc import Sequence
from datetime import UTC, datetime

from src.config.constants import SQUARE_ASPECT_TOLERANCE
from src.domain.enums import SelectionOrder, VideoOrientation, VideoQueueStatus
from src.domain.models import FilterEvaluation, UploadProfile, VideoQueueItem

_SECURE_RANDOM = secrets.SystemRandom()


def _parse_iso_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _matches_orientation(width: int, height: int, target: VideoOrientation) -> bool:
    if target == VideoOrientation.ANY:
        return True
    ratio_diff = abs(width - height) / max(width, height)
    if target == VideoOrientation.SQUARE:
        return ratio_diff <= SQUARE_ASPECT_TOLERANCE
    if target == VideoOrientation.PORTRAIT:
        return height > width and ratio_diff > SQUARE_ASPECT_TOLERANCE
    return width > height and ratio_diff > SQUARE_ASPECT_TOLERANCE


def evaluate_video_for_profile(
    video: VideoQueueItem,
    profile: UploadProfile,
) -> FilterEvaluation:
    """Prüft, ob ein Video alle Schemaregeln von `profile` erfüllt."""
    reasons: list[str] = []

    if video.status != VideoQueueStatus.QUEUED:
        reasons.append(f"Status ist '{video.status.value}' statt 'queued'")

    if video.drive_trashed:
        reasons.append("Datei liegt bereits im Drive-Papierkorb")

    if video.width and video.height:
        if not _matches_orientation(video.width, video.height, profile.orientation):
            reasons.append(
                f"Orientierung {video.width}x{video.height} passt nicht zu '{profile.orientation.value}'"
            )
        aspect = video.width / video.height
        if profile.min_aspect_ratio is not None and aspect < profile.min_aspect_ratio:
            reasons.append(
                f"Seitenverhältnis {aspect:.2f} unter Minimum {profile.min_aspect_ratio:.2f}"
            )
        if profile.max_aspect_ratio is not None and aspect > profile.max_aspect_ratio:
            reasons.append(
                f"Seitenverhältnis {aspect:.2f} über Maximum {profile.max_aspect_ratio:.2f}"
            )
        if profile.min_width is not None and video.width < profile.min_width:
            reasons.append(f"Breite {video.width}px < {profile.min_width}px")
        if profile.min_height is not None and video.height < profile.min_height:
            reasons.append(f"Höhe {video.height}px < {profile.min_height}px")

    if video.duration_seconds is not None:
        if (
            profile.min_duration_seconds is not None
            and video.duration_seconds < profile.min_duration_seconds
        ):
            reasons.append(
                f"Länge {video.duration_seconds:.1f}s < {profile.min_duration_seconds:.1f}s"
            )
        if (
            profile.max_duration_seconds is not None
            and video.duration_seconds > profile.max_duration_seconds
        ):
            reasons.append(
                f"Länge {video.duration_seconds:.1f}s > {profile.max_duration_seconds:.1f}s"
            )

    rec_dt = _parse_iso_datetime(video.recorded_at or video.imported_at)
    from_dt = _parse_iso_datetime(profile.date_from)
    to_dt = _parse_iso_datetime(profile.date_to)
    if rec_dt is not None:
        if from_dt is not None and rec_dt < from_dt:
            reasons.append(f"Aufnahmedatum {rec_dt.date()} vor {from_dt.date()}")
        if to_dt is not None and rec_dt > to_dt:
            reasons.append(f"Aufnahmedatum {rec_dt.date()} nach {to_dt.date()}")

    lower_name = video.filename.lower()
    if profile.include_filename_patterns and not any(
        fnmatch.fnmatch(lower_name, pat.lower()) for pat in profile.include_filename_patterns
    ):
        reasons.append("Dateiname erfüllt kein Include-Muster")

    if profile.exclude_filename_patterns and any(
        fnmatch.fnmatch(lower_name, pat.lower()) for pat in profile.exclude_filename_patterns
    ):
        reasons.append("Dateiname durch Exclude-Muster ausgeschlossen")

    return FilterEvaluation(matched=not reasons, reasons=tuple(reasons))


def _sort_key_timestamp(video: VideoQueueItem) -> str:
    return video.recorded_at or video.imported_at or ""


def select_candidates(
    videos: Sequence[VideoQueueItem],
    profile: UploadProfile,
) -> list[VideoQueueItem]:
    """Filtert und sortiert geeignete Queue-Videos gemäß Profilreihenfolge."""
    eligible = [v for v in videos if evaluate_video_for_profile(v, profile).matched]

    if profile.selection_order == SelectionOrder.OLDEST_FIRST:
        return sorted(eligible, key=lambda v: (_sort_key_timestamp(v), v.filename, v.id))
    if profile.selection_order == SelectionOrder.NEWEST_FIRST:
        return sorted(
            eligible,
            key=lambda v: (_sort_key_timestamp(v), v.filename, v.id),
            reverse=True,
        )

    shuffled = list(eligible)
    _SECURE_RANDOM.shuffle(shuffled)
    return shuffled
