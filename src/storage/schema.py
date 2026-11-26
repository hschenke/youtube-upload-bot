"""Idempotentes Datenbankschema für Profile, Video-Queue, Upload-Läufe und Settings."""

from __future__ import annotations

SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS upload_profiles (
        name TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        orientation TEXT NOT NULL DEFAULT 'portrait',
        min_aspect_ratio REAL,
        max_aspect_ratio REAL,
        min_duration_seconds REAL,
        max_duration_seconds REAL,
        min_width INTEGER,
        min_height INTEGER,
        date_from TEXT,
        date_to TEXT,
        include_filename_patterns_json TEXT NOT NULL DEFAULT '[]',
        exclude_filename_patterns_json TEXT NOT NULL DEFAULT '[]',
        selection_order TEXT NOT NULL DEFAULT 'oldest_first',
        max_uploads_per_run INTEGER NOT NULL DEFAULT 1,
        privacy_status TEXT NOT NULL DEFAULT 'public',
        category_id TEXT NOT NULL DEFAULT '22',
        made_for_kids INTEGER NOT NULL DEFAULT 0,
        language TEXT NOT NULL DEFAULT 'en',
        required_hashtags_json TEXT NOT NULL DEFAULT '[]',
        default_tags_json TEXT NOT NULL DEFAULT '[]',
        description_footer TEXT NOT NULL DEFAULT '',
        ai_prompt TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS video_queue (
        id TEXT PRIMARY KEY,
        drive_file_id TEXT NOT NULL UNIQUE,
        filename TEXT NOT NULL,
        mime_type TEXT NOT NULL DEFAULT 'video/mp4',
        photos_media_id TEXT,
        content_sha256 TEXT,
        size_bytes INTEGER NOT NULL DEFAULT 0,
        width INTEGER,
        height INTEGER,
        duration_seconds REAL,
        fps REAL,
        orientation TEXT,
        recorded_at TEXT,
        imported_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued',
        matched_profile TEXT,
        youtube_video_id TEXT,
        youtube_url TEXT,
        title_override TEXT,
        description_override TEXT,
        hashtags_override_json TEXT NOT NULL DEFAULT '[]',
        generated_title TEXT,
        generated_description TEXT,
        generated_hashtags_json TEXT NOT NULL DEFAULT '[]',
        drive_trashed INTEGER NOT NULL DEFAULT 0,
        error_message TEXT,
        uploaded_at TEXT,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS upload_runs (
        run_id TEXT PRIMARY KEY,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        trigger_source TEXT NOT NULL,
        profile_name TEXT NOT NULL DEFAULT '',
        dry_run INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'success',
        scanned_count INTEGER NOT NULL DEFAULT 0,
        eligible_count INTEGER NOT NULL DEFAULT 0,
        uploaded_count INTEGER NOT NULL DEFAULT 0,
        skipped_count INTEGER NOT NULL DEFAULT 0,
        failed_count INTEGER NOT NULL DEFAULT 0,
        uploaded_video_ids_json TEXT NOT NULL DEFAULT '[]',
        summary_message TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_video_queue_status ON video_queue(status)",
    "CREATE INDEX IF NOT EXISTS idx_video_queue_photos_id ON video_queue(photos_media_id)",
    "CREATE INDEX IF NOT EXISTS idx_video_queue_sha256 ON video_queue(content_sha256)",
    "CREATE INDEX IF NOT EXISTS idx_upload_runs_started ON upload_runs(started_at DESC)",
)
