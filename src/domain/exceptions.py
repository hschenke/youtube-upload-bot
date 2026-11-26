"""Anwendungsspezifische Exception-Hierarchie für isolierte Fehlerbehandlung."""

from __future__ import annotations


class BotError(Exception):
    """Basisklasse für alle fachlichen und technischen Fehler des Bots."""


class ConfigurationError(BotError):
    """Fehlende oder ungültige Konfiguration."""


class InputValidationError(BotError):
    """Ungültige Eingabe- oder Sicherheitsprüfung."""


class StorageError(BotError):
    """Allgemeiner Fehler bei Datenbankoperationen."""


class StorageConnectionError(StorageError):
    """Verbindungs- oder HTTP-Fehler gegenüber SQLite/Turso."""


class GoogleAuthError(BotError):
    """Fehler beim Erzeugen oder Aktualisieren von Google OAuth Credentials."""


class PhotosPickerError(BotError):
    """Fehler bei der Google Photos Picker API."""


class DriveStagingError(BotError):
    """Fehler beim Lesen, Schreiben oder Löschen im Google Drive Staging-Ordner."""


class MediaProbeError(BotError):
    """Fehler beim Auslesen technischer Video-Metadaten (z. B. via ffprobe)."""


class YouTubeUploadError(BotError):
    """Fehler beim YouTube Data API v3 Upload oder Kanal-Abruf."""


class LLMProviderError(BotError):
    """Fehler bei der Video-Analyse mit Gemini."""


class NotificationError(BotError):
    """Fehler beim Versand von Benachrichtigungen."""


class DispatchError(BotError):
    """Fehler beim Auslösen eines GitHub Actions Workflows."""
