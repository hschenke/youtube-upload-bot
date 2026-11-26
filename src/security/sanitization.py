"""Input-Validierung, Path-Traversal-Schutz, SSRF-Guard und Log-Maskierung."""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from urllib.parse import urlparse

from src.config.constants import (
    ALLOWED_GOOGLE_MEDIA_HOST_SUFFIXES,
    YOUTUBE_MAX_DESCRIPTION_LENGTH,
    YOUTUBE_MAX_TITLE_LENGTH,
)
from src.domain.exceptions import InputValidationError

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_FILENAME_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def sanitize_filename(raw_name: str, fallback: str = "video.mp4") -> str:
    """Bereinigt einen Dateinamen von Pfad-Separatoren und unsicheren Zeichen."""
    base = Path(str(raw_name or "").replace("\\", "/")).name
    base = _CONTROL_CHARS_RE.sub("", base).strip()
    cleaned = _FILENAME_UNSAFE_RE.sub("_", base).strip("._")
    if not cleaned:
        return fallback
    return cleaned[:160]


def get_safe_filepath(base_dir: Path, filename: str) -> Path:
    """Löst einen Dateipfad innerhalb von `base_dir` sicher auf (Path-Traversal-Schutz)."""
    safe_name = sanitize_filename(filename)
    resolved_base = base_dir.resolve()
    target_path = (resolved_base / safe_name).resolve()
    if not target_path.is_relative_to(resolved_base):
        raise InputValidationError(f"Ungültiger Dateipfad außerhalb des Zielverzeichnisses: '{filename}'.")
    return target_path


def validate_google_media_url(raw_url: str) -> str:
    """Validiert Google-Picker-Medien-URLs strikt gegen SSRF und Bearer-Token-Leaks."""
    cleaned = (raw_url or "").strip()
    parsed = urlparse(cleaned)
    if parsed.scheme != "https" or not parsed.netloc:
        raise InputValidationError("Medien-URL muss HTTPS mit gültigem Host verwenden.")

    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname:
        raise InputValidationError("Medien-URL enthält keinen gültigen Hostnamen.")

    try:
        ip_obj = ipaddress.ip_address(hostname)
        if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved:
            raise InputValidationError("Direkte/private IP-Adressen sind für Medien-Downloads blockiert.")
    except ValueError:
        pass

    if not any(
        hostname == suffix.lstrip(".") or hostname.endswith(suffix)
        for suffix in ALLOWED_GOOGLE_MEDIA_HOST_SUFFIXES
    ):
        raise InputValidationError(f"Nicht vertrauenswürdiger Medien-Host blockiert: '{hostname}'.")

    return cleaned


def sanitize_display_url(raw_url: str) -> str:
    """Erlaubt ausschließlich `http://` und `https://` URLs für anklickbare Links."""
    cleaned = (raw_url or "").strip()
    parsed = urlparse(cleaned)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return cleaned
    return "#"


def sanitize_youtube_text(raw_text: str, max_length: int, single_line: bool = False) -> str:
    """Entfernt spitze Klammern (`<`, `>`) und Steuerzeichen für die YouTube Data API."""
    cleaned = _CONTROL_CHARS_RE.sub("", str(raw_text or ""))
    cleaned = cleaned.replace("<", "").replace(">", "")
    cleaned = " ".join(cleaned.split()) if single_line else cleaned.strip()

    if len(cleaned) <= max_length:
        return cleaned
    if single_line and max_length > 1:
        return cleaned[: max_length - 1].rstrip() + "…"
    return cleaned[:max_length].rstrip()


def sanitize_youtube_title(raw_title: str) -> str:
    title = sanitize_youtube_text(raw_title, YOUTUBE_MAX_TITLE_LENGTH, single_line=True)
    return title or "Untitled Video"


def sanitize_youtube_description(raw_description: str) -> str:
    return sanitize_youtube_text(raw_description, YOUTUBE_MAX_DESCRIPTION_LENGTH, single_line=False)


def validate_email_address(raw_email: str) -> str:
    """Prüft eine E-Mail-Adresse gegen ein striktes Format ohne Header-Injection."""
    cleaned = (raw_email or "").strip()
    if not cleaned or len(cleaned) > 254 or any(c in cleaned for c in ("\r", "\n")):
        raise InputValidationError("Ungültige E-Mail-Adresse.")
    if not _EMAIL_RE.match(cleaned):
        raise InputValidationError("E-Mail-Adresse entspricht nicht dem gültigen Format.")
    return cleaned


def mask_email_for_log(email: str) -> str:
    """Maskiert eine E-Mail-Adresse für PII-freie Logs (`ho***@example.com`)."""
    cleaned = (email or "").strip()
    if "@" not in cleaned:
        return "***"
    local, domain = cleaned.split("@", 1)
    prefix = local[:2] if len(local) >= 2 else local[:1]
    return f"{prefix}***@{domain}"
