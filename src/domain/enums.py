"""Typisierte Enumerationen für Profile, Queue-Status, Läufe und Berechtigungen."""

from __future__ import annotations

from enum import StrEnum


class VideoOrientation(StrEnum):
    PORTRAIT = "portrait"
    LANDSCAPE = "landscape"
    SQUARE = "square"
    ANY = "any"


class SelectionOrder(StrEnum):
    OLDEST_FIRST = "oldest_first"
    NEWEST_FIRST = "newest_first"
    RANDOM = "random"


class PrivacyStatus(StrEnum):
    PUBLIC = "public"
    UNLISTED = "unlisted"
    PRIVATE = "private"


class VideoQueueStatus(StrEnum):
    QUEUED = "queued"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    SKIPPED = "skipped"
    FAILED = "failed"


class RunStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    EMPTY = "empty"


class TriggerSource(StrEnum):
    GITHUB_ACTIONS = "github_actions"
    CLI = "cli"
    STREAMLIT = "streamlit"


class AuthRole(StrEnum):
    ADMIN = "admin"
    READONLY = "readonly"
    GUEST = "guest"
