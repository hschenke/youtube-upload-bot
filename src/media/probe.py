"""Video-Inspektion mit `ffprobe` (inkl. Rotations-Erkennung) und SHA-256-Hashing."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from src.config.constants import FFPROBE_TIMEOUT_SECONDS, HASH_CHUNK_SIZE_BYTES
from src.domain.exceptions import MediaProbeError
from src.domain.models import MediaProbeResult


def compute_file_sha256(file_path: Path) -> str:
    """Berechnet den SHA-256-Hash einer Videodatei speicherschonend per Chunk-Streaming."""
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        while True:
            chunk = handle.read(HASH_CHUNK_SIZE_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _parse_fps(raw_rate: str | None) -> float | None:
    if not raw_rate or raw_rate in {"0/0", "0"}:
        return None
    if "/" in raw_rate:
        num_str, den_str = raw_rate.split("/", 1)
        try:
            num = float(num_str)
            den = float(den_str)
            return round(num / den, 3) if den > 0 else None
        except ValueError:
            return None
    try:
        return round(float(raw_rate), 3)
    except ValueError:
        return None


def _extract_rotation_degrees(video_stream: dict[str, Any]) -> int:
    """Liest Rotations-Metadaten aus `tags.rotate` sowie `side_data_list[].rotation`."""
    tags = video_stream.get("tags")
    if isinstance(tags, dict) and tags.get("rotate") is not None:
        try:
            return int(float(tags["rotate"])) % 360
        except (ValueError, TypeError):
            pass

    for side_data in video_stream.get("side_data_list") or []:
        if not isinstance(side_data, dict):
            continue
        if side_data.get("rotation") is not None:
            try:
                return int(round(float(side_data["rotation"]))) % 360
            except (ValueError, TypeError):
                continue
    return 0


def parse_ffprobe_payload(payload: dict[str, Any], file_size_bytes: int = 0) -> MediaProbeResult:
    """Wandelt eine `ffprobe -print_format json`-Ausgabe in `MediaProbeResult` um."""
    streams = payload.get("streams")
    if not isinstance(streams, list):
        raise MediaProbeError("ffprobe lieferte keine gültige Stream-Liste.")

    video_stream = next(
        (s for s in streams if isinstance(s, dict) and s.get("codec_type") == "video"),
        None,
    )
    if video_stream is None:
        raise MediaProbeError("Datei enthält keinen Video-Stream.")

    has_audio = any(isinstance(s, dict) and s.get("codec_type") == "audio" for s in streams)
    raw_width = int(video_stream.get("width") or 0)
    raw_height = int(video_stream.get("height") or 0)
    if raw_width <= 0 or raw_height <= 0:
        raise MediaProbeError("Ungültige Video-Abmessungen aus ffprobe.")

    rotation = _extract_rotation_degrees(video_stream)
    if abs(rotation) % 180 == 90:
        display_width, display_height = raw_height, raw_width
    else:
        display_width, display_height = raw_width, raw_height

    fmt = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    raw_duration = video_stream.get("duration") or fmt.get("duration") or 0.0
    try:
        duration_seconds = round(float(raw_duration), 3)
    except (ValueError, TypeError) as exc:
        raise MediaProbeError("Ungültige Videolänge aus ffprobe.") from exc

    fmt_tags = fmt.get("tags") if isinstance(fmt.get("tags"), dict) else {}
    stream_tags = video_stream.get("tags") if isinstance(video_stream.get("tags"), dict) else {}
    creation_time = fmt_tags.get("creation_time") or stream_tags.get("creation_time")

    fps = _parse_fps(video_stream.get("avg_frame_rate")) or _parse_fps(
        video_stream.get("r_frame_rate")
    )

    return MediaProbeResult(
        raw_width=raw_width,
        raw_height=raw_height,
        display_width=display_width,
        display_height=display_height,
        rotation_degrees=rotation,
        duration_seconds=duration_seconds,
        fps=fps,
        video_codec=str(video_stream.get("codec_name") or ""),
        has_audio=has_audio,
        creation_time=str(creation_time) if creation_time else None,
        file_size_bytes=file_size_bytes,
    )


def probe_video_file(video_path: Path) -> MediaProbeResult:
    """Führt `ffprobe` sicher (`shell=False`) auf einer lokalen Videodatei aus."""
    if not video_path.exists():
        raise MediaProbeError(f"Videodatei existiert nicht: {video_path.name}")

    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(video_path),
    ]
    try:
        completed = subprocess.run(  # noqa: S603
            cmd,
            shell=False,
            capture_output=True,
            text=True,
            timeout=FFPROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise MediaProbeError(
            "ffprobe wurde nicht gefunden. Bitte `ffmpeg` installieren."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaProbeError(f"ffprobe Timeout nach {FFPROBE_TIMEOUT_SECONDS}s.") from exc

    if completed.returncode != 0 or not completed.stdout.strip():
        raise MediaProbeError(f"ffprobe fehlgeschlagen für '{video_path.name}'.")

    try:
        payload = json.loads(completed.stdout)
    except ValueError as exc:
        raise MediaProbeError("ffprobe lieferte ungültiges JSON.") from exc

    return parse_ffprobe_payload(payload, file_size_bytes=video_path.stat().st_size)
