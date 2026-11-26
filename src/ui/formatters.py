"""Formatierungs- und Darstellungs-Helfer für die Streamlit UI."""

from __future__ import annotations

from src.domain.enums import RunStatus, VideoQueueStatus


def format_bytes(num_bytes: int) -> str:
    if num_bytes <= 0:
        return "0 B"
    units = ("B", "KB", "MB", "GB")
    size = float(num_bytes)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{num_bytes} B"


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "–"
    total = int(round(seconds))
    mins, secs = divmod(total, 60)
    hours, mins = divmod(mins, 60)
    if hours > 0:
        return f"{hours}:{mins:02d}:{secs:02d}"
    return f"{mins}:{secs:02d}"


def format_resolution(width: int | None, height: int | None) -> str:
    if not width or not height:
        return "unbekannt"
    return f"{width}×{height}"


def format_status_badge(status: VideoQueueStatus) -> str:
    mapping = {
        VideoQueueStatus.QUEUED: "🕒 Warteschlange",
        VideoQueueStatus.UPLOADING: "⬆️ Lädt hoch",
        VideoQueueStatus.UPLOADED: "✅ Hochgeladen",
        VideoQueueStatus.SKIPPED: "⏭️ Übersprungen",
        VideoQueueStatus.FAILED: "❌ Fehlgeschlagen",
    }
    return mapping.get(status, status.value)


def format_run_status_badge(status: RunStatus) -> str:
    mapping = {
        RunStatus.SUCCESS: "✅ Erfolg",
        RunStatus.PARTIAL: "🟡 Teilweise",
        RunStatus.FAILED: "❌ Fehler",
        RunStatus.EMPTY: "📭 Queue leer",
    }
    return mapping.get(status, status.value)
