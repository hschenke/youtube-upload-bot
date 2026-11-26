"""Zentrale, benannte Konstanten für youtube-upload-bot (keine Magic Values)."""

from __future__ import annotations

# --- Pfade & Defaults ---
DEFAULT_LOCAL_DB_PATH = "data/youtube_bot.db"
DEFAULT_SETTINGS_YAML_PATH = "config/settings.yaml"
DEFAULT_STAGING_FOLDER_NAME = "youtube-upload-bot-staging"

# --- Google API Endpunkte & Scopes ---
GOOGLE_OAUTH_TOKEN_URI = "https://oauth2.googleapis.com/token"  # noqa: S105
PHOTOS_PICKER_API_BASE = "https://photospicker.googleapis.com/v1"
YOUTUBE_WATCH_URL_TEMPLATE = "https://www.youtube.com/watch?v={video_id}"
YOUTUBE_SHORTS_URL_TEMPLATE = "https://youtube.com/shorts/{video_id}"

GOOGLE_REQUIRED_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/photospicker.mediaitems.readonly",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
)
GOOGLE_LEAST_PRIVILEGE_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/photospicker.mediaitems.readonly",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
)

ALLOWED_GOOGLE_MEDIA_HOST_SUFFIXES: tuple[str, ...] = (
    ".googleusercontent.com",
    ".googleapis.com",
)

# --- HTTP, Streaming & Dateilimits ---
DEFAULT_HTTP_TIMEOUT_SECONDS = 30.0
MEDIA_DOWNLOAD_TIMEOUT_SECONDS = (10.0, 120.0)
DRIVE_CHUNK_SIZE_BYTES = 5 * 1024 * 1024
YOUTUBE_CHUNK_SIZE_BYTES = 5 * 1024 * 1024
STREAM_READ_CHUNK_SIZE_BYTES = 1024 * 1024
HASH_CHUNK_SIZE_BYTES = 1024 * 1024
MAX_VIDEO_FILE_SIZE_BYTES = 512 * 1024 * 1024
DEFAULT_HTTP_RETRIES = 3
RETRY_BACKOFF_BASE_SECONDS = 1.5

# --- FFprobe & Medienanalyse ---
FFPROBE_TIMEOUT_SECONDS = 30
SQUARE_ASPECT_TOLERANCE = 0.05
DEFAULT_PICKER_MAX_ITEMS = 50
DEFAULT_SHORTS_MIN_DURATION = 3.0
DEFAULT_SHORTS_MAX_DURATION = 180.0

# --- YouTube Limits ---
YOUTUBE_MAX_TITLE_LENGTH = 100
YOUTUBE_MAX_DESCRIPTION_LENGTH = 5000
YOUTUBE_MAX_TAG_CHARS = 500
YOUTUBE_DEFAULT_CATEGORY_ID = "22"
YOUTUBE_UPLOAD_MAX_RETRIES = 3

# --- Gemini API (aktuelle Modelle; keine Legacy-Modelle!) ---
CANDIDATE_MODELS: tuple[str, ...] = (
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-4-argon",
)
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
LLM_TIMEOUT_SECONDS = 90.0
LLM_MAX_ATTEMPTS = 3
GEMINI_FILE_POLL_INTERVAL_SECONDS = 3.0
GEMINI_FILE_MAX_WAIT_SECONDS = 120.0

# --- Datenbank & Turso ---
TURSO_HTTP_TIMEOUT_SECONDS = 25.0
TURSO_BATCH_SIZE = 20
SQLITE_BUSY_TIMEOUT_MS = 10000
DEFAULT_QUERY_LIMIT = 200

# --- E-Mail & GitHub Actions ---
EMAIL_HTTP_TIMEOUT_SECONDS = 20.0
GITHUB_API_TIMEOUT_SECONDS = 20.0
DEFAULT_SMTP_PORT = 587

# --- Authentifizierung & Rate Limiting ---
ADMIN_TOKEN_MAX_AGE_SECONDS = 86400
CLOCK_SKEW_TOLERANCE_SECONDS = 60
MAX_FAILED_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 300
