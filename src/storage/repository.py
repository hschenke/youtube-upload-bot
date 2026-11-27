"""Repository-Schicht für Profile, Video-Queue, Duplikatschutz und Upload-Läufe."""

from __future__ import annotations

import json
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from src.config.constants import DEFAULT_QUERY_LIMIT, OAUTH_STATE_TTL_SECONDS
from src.config.settings import AppSettings
from src.domain.enums import VideoQueueStatus
from src.domain.models import (
    DriveVideoFile,
    GoogleAccountRecord,
    OAuthStateRecord,
    UploadProfile,
    UploadRunRecord,
    VideoQueueItem,
)
from src.storage.executor import SqlExecutor
from src.storage.row_mappers import (
    row_to_google_account,
    row_to_oauth_state,
    row_to_upload_profile,
    row_to_upload_run,
    row_to_video_queue_item,
)
from src.storage.schema import SCHEMA_STATEMENTS
from src.storage.sqlite_executor import SqliteExecutor
from src.storage.turso_executor import TursoExecutor


def utc_now_iso() -> str:
    """Liefert den aktuellen UTC-Zeitstempel im ISO-8601-Format."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def infer_orientation(width: int | None, height: int | None) -> str | None:
    if not width or not height:
        return None
    ratio_diff = abs(width - height) / max(width, height)
    if ratio_diff <= 0.05:
        return "square"
    return "portrait" if height > width else "landscape"


class SqlBotRepository:
    """Zentrales Repository für alle Persistenzoperationen (SQLite & Turso)."""

    def __init__(self, executor: SqlExecutor) -> None:
        self._executor = executor
        self._ensure_schema()

    @property
    def backend_name(self) -> str:
        return self._executor.backend_name

    def _ensure_schema(self) -> None:
        statements = [(stmt, ()) for stmt in SCHEMA_STATEMENTS]
        self._executor.execute_batch(statements)

    def close(self) -> None:
        self._executor.close()

    # --- Profile ---

    def seed_default_profiles(self, profiles: Sequence[UploadProfile]) -> None:
        """Legt YAML-Standardprofile nur an, wenn sie noch nicht in der DB existieren."""
        existing = {p.name for p in self.list_profiles()}
        for profile in profiles:
            if profile.name not in existing:
                self.upsert_profile(profile)

    def list_profiles(self, enabled_only: bool = False) -> list[UploadProfile]:
        sql = "SELECT * FROM upload_profiles"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY name ASC"
        res = self._executor.execute(sql)
        return [row_to_upload_profile(row) for row in res.rows]

    def get_profile(self, name: str) -> UploadProfile | None:
        res = self._executor.execute(
            "SELECT * FROM upload_profiles WHERE name = ? LIMIT 1",
            (name.strip().lower(),),
        )
        return row_to_upload_profile(res.rows[0]) if res.rows else None

    def upsert_profile(self, profile: UploadProfile) -> None:
        now = utc_now_iso()
        self._executor.execute(
            """
            INSERT INTO upload_profiles (
                name, display_name, enabled, orientation,
                min_aspect_ratio, max_aspect_ratio,
                min_duration_seconds, max_duration_seconds,
                min_width, min_height, date_from, date_to,
                include_filename_patterns_json, exclude_filename_patterns_json,
                selection_order, max_uploads_per_run,
                privacy_status, category_id, made_for_kids, language,
                required_hashtags_json, default_tags_json,
                description_footer, ai_prompt, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                display_name = excluded.display_name,
                enabled = excluded.enabled,
                orientation = excluded.orientation,
                min_aspect_ratio = excluded.min_aspect_ratio,
                max_aspect_ratio = excluded.max_aspect_ratio,
                min_duration_seconds = excluded.min_duration_seconds,
                max_duration_seconds = excluded.max_duration_seconds,
                min_width = excluded.min_width,
                min_height = excluded.min_height,
                date_from = excluded.date_from,
                date_to = excluded.date_to,
                include_filename_patterns_json = excluded.include_filename_patterns_json,
                exclude_filename_patterns_json = excluded.exclude_filename_patterns_json,
                selection_order = excluded.selection_order,
                max_uploads_per_run = excluded.max_uploads_per_run,
                privacy_status = excluded.privacy_status,
                category_id = excluded.category_id,
                made_for_kids = excluded.made_for_kids,
                language = excluded.language,
                required_hashtags_json = excluded.required_hashtags_json,
                default_tags_json = excluded.default_tags_json,
                description_footer = excluded.description_footer,
                ai_prompt = excluded.ai_prompt,
                updated_at = excluded.updated_at
            """,
            (
                profile.name.strip().lower(),
                profile.display_name.strip(),
                1 if profile.enabled else 0,
                profile.orientation.value,
                profile.min_aspect_ratio,
                profile.max_aspect_ratio,
                profile.min_duration_seconds,
                profile.max_duration_seconds,
                profile.min_width,
                profile.min_height,
                profile.date_from,
                profile.date_to,
                json.dumps(list(profile.include_filename_patterns)),
                json.dumps(list(profile.exclude_filename_patterns)),
                profile.selection_order.value,
                int(profile.max_uploads_per_run),
                profile.privacy_status.value,
                profile.category_id,
                1 if profile.made_for_kids else 0,
                profile.language,
                json.dumps(list(profile.required_hashtags)),
                json.dumps(list(profile.default_tags)),
                profile.description_footer,
                profile.ai_prompt,
                now,
            ),
        )

    # --- Video-Queue & Duplikatschutz ---

    def is_already_uploaded(
        self,
        *,
        drive_file_id: str | None = None,
        photos_media_id: str | None = None,
        content_sha256: str | None = None,
    ) -> bool:
        """Dreifache Duplikatsprüfung über Drive-ID, Photos-ID und Content-SHA256."""
        clauses: list[str] = []
        params: list[str] = []
        if drive_file_id:
            clauses.append("drive_file_id = ?")
            params.append(drive_file_id)
        if photos_media_id:
            clauses.append("photos_media_id = ?")
            params.append(photos_media_id)
        if content_sha256:
            clauses.append("content_sha256 = ?")
            params.append(content_sha256)
        if not clauses:
            return False

        where_expr = " OR ".join(clauses)
        res = self._executor.execute(
            f"SELECT id FROM video_queue WHERE status = 'uploaded' AND ({where_expr}) LIMIT 1",  # noqa: S608
            params,
        )
        return bool(res.rows)

    def get_video_by_id(self, video_id: str) -> VideoQueueItem | None:
        res = self._executor.execute(
            "SELECT * FROM video_queue WHERE id = ? LIMIT 1",
            (video_id,),
        )
        return row_to_video_queue_item(res.rows[0]) if res.rows else None

    def get_video_by_drive_id(self, drive_file_id: str) -> VideoQueueItem | None:
        res = self._executor.execute(
            "SELECT * FROM video_queue WHERE drive_file_id = ? LIMIT 1",
            (drive_file_id,),
        )
        return row_to_video_queue_item(res.rows[0]) if res.rows else None

    def upsert_staged_video(
        self,
        drive_file: DriveVideoFile,
        *,
        width: int | None = None,
        height: int | None = None,
        duration_seconds: float | None = None,
        fps: float | None = None,
        content_sha256: str | None = None,
    ) -> VideoQueueItem:
        """Synchronisiert eine Drive-Staging-Datei idempotent in `video_queue`."""
        now = utc_now_iso()
        existing = self.get_video_by_drive_id(drive_file.drive_file_id)
        eff_width = width if width is not None else drive_file.width
        eff_height = height if height is not None else drive_file.height
        eff_duration = (
            duration_seconds if duration_seconds is not None else drive_file.duration_seconds
        )
        orientation = infer_orientation(eff_width, eff_height)
        recorded_at = drive_file.original_created_at or drive_file.created_time

        if existing is None:
            new_id = f"vid_{secrets.token_hex(8)}"
            self._executor.execute(
                """
                INSERT INTO video_queue (
                    id, drive_file_id, filename, mime_type, photos_media_id, content_sha256,
                    size_bytes, width, height, duration_seconds, fps, orientation,
                    recorded_at, imported_at, status, drive_trashed, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id,
                    drive_file.drive_file_id,
                    drive_file.filename,
                    drive_file.mime_type,
                    drive_file.photos_media_id,
                    content_sha256,
                    drive_file.size_bytes,
                    eff_width,
                    eff_height,
                    eff_duration,
                    fps,
                    orientation,
                    recorded_at,
                    now,
                    VideoQueueStatus.QUEUED.value,
                    1 if drive_file.trashed else 0,
                    now,
                ),
            )
            created = self.get_video_by_id(new_id)
            if created is None:
                raise RuntimeError("Video konnte nach Insert nicht gelesen werden.")
            return created

        self._executor.execute(
            """
            UPDATE video_queue SET
                filename = ?,
                mime_type = ?,
                photos_media_id = COALESCE(photos_media_id, ?),
                content_sha256 = COALESCE(content_sha256, ?),
                size_bytes = CASE WHEN ? > 0 THEN ? ELSE size_bytes END,
                width = COALESCE(?, width),
                height = COALESCE(?, height),
                duration_seconds = COALESCE(?, duration_seconds),
                fps = COALESCE(?, fps),
                orientation = COALESCE(?, orientation),
                recorded_at = COALESCE(recorded_at, ?),
                drive_trashed = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                drive_file.filename,
                drive_file.mime_type,
                drive_file.photos_media_id,
                content_sha256,
                drive_file.size_bytes,
                drive_file.size_bytes,
                eff_width,
                eff_height,
                eff_duration,
                fps,
                orientation,
                recorded_at,
                1 if drive_file.trashed else 0,
                now,
                existing.id,
            ),
        )
        updated = self.get_video_by_id(existing.id)
        if updated is None:
            raise RuntimeError("Video konnte nach Update nicht gelesen werden.")
        return updated

    def update_probe_metadata(
        self,
        video_id: str,
        *,
        width: int,
        height: int,
        duration_seconds: float,
        fps: float | None,
        content_sha256: str,
        recorded_at: str | None = None,
    ) -> None:
        orientation = infer_orientation(width, height)
        self._executor.execute(
            """
            UPDATE video_queue SET
                width = ?,
                height = ?,
                duration_seconds = ?,
                fps = ?,
                orientation = ?,
                content_sha256 = ?,
                recorded_at = COALESCE(recorded_at, ?),
                updated_at = ?
            WHERE id = ?
            """,
            (
                width,
                height,
                duration_seconds,
                fps,
                orientation,
                content_sha256,
                recorded_at,
                utc_now_iso(),
                video_id,
            ),
        )

    def list_videos(
        self,
        status: VideoQueueStatus | None = None,
        limit: int = DEFAULT_QUERY_LIMIT,
    ) -> list[VideoQueueItem]:
        if status is not None:
            res = self._executor.execute(
                "SELECT * FROM video_queue WHERE status = ? ORDER BY imported_at DESC LIMIT ?",
                (status.value, int(limit)),
            )
        else:
            res = self._executor.execute(
                "SELECT * FROM video_queue ORDER BY imported_at DESC LIMIT ?",
                (int(limit),),
            )
        return [row_to_video_queue_item(row) for row in res.rows]

    def claim_video_for_upload(self, video_id: str, profile_name: str) -> bool:
        """Setzt Status atomar auf `uploading`, falls das Video noch `queued` ist."""
        res = self._executor.execute(
            """
            UPDATE video_queue
            SET status = ?, matched_profile = ?, error_message = NULL, updated_at = ?
            WHERE id = ? AND status = ?
            """,
            (
                VideoQueueStatus.UPLOADING.value,
                profile_name,
                utc_now_iso(),
                video_id,
                VideoQueueStatus.QUEUED.value,
            ),
        )
        return res.affected_rows > 0

    def mark_video_uploaded(
        self,
        video_id: str,
        *,
        profile_name: str,
        youtube_video_id: str,
        youtube_url: str,
        generated_title: str,
        generated_description: str,
        generated_hashtags: Sequence[str],
        drive_trashed: bool,
    ) -> None:
        now = utc_now_iso()
        self._executor.execute(
            """
            UPDATE video_queue SET
                status = ?,
                matched_profile = ?,
                youtube_video_id = ?,
                youtube_url = ?,
                generated_title = ?,
                generated_description = ?,
                generated_hashtags_json = ?,
                drive_trashed = ?,
                error_message = NULL,
                uploaded_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                VideoQueueStatus.UPLOADED.value,
                profile_name,
                youtube_video_id,
                youtube_url,
                generated_title,
                generated_description,
                json.dumps(list(generated_hashtags)),
                1 if drive_trashed else 0,
                now,
                now,
                video_id,
            ),
        )

    def mark_drive_trashed(self, video_id: str, trashed: bool = True) -> None:
        self._executor.execute(
            "UPDATE video_queue SET drive_trashed = ?, updated_at = ? WHERE id = ?",
            (1 if trashed else 0, utc_now_iso(), video_id),
        )

    def update_video_status(
        self,
        video_id: str,
        status: VideoQueueStatus,
        *,
        error_message: str | None = None,
    ) -> None:
        self._executor.execute(
            "UPDATE video_queue SET status = ?, error_message = ?, updated_at = ? WHERE id = ?",
            (status.value, error_message, utc_now_iso(), video_id),
        )

    def update_manual_metadata(
        self,
        video_id: str,
        *,
        title_override: str | None,
        description_override: str | None,
        hashtags_override: Sequence[str],
    ) -> None:
        self._executor.execute(
            """
            UPDATE video_queue SET
                title_override = ?,
                description_override = ?,
                hashtags_override_json = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                title_override or None,
                description_override or None,
                json.dumps(list(hashtags_override)),
                utc_now_iso(),
                video_id,
            ),
        )

    def mark_missing_drive_videos_skipped(self, active_drive_ids: set[str]) -> int:
        """Markiert lokal als `queued` geführte Videos, die in Drive nicht mehr existieren."""
        queued = self.list_videos(status=VideoQueueStatus.QUEUED, limit=1000)
        skipped_count = 0
        for item in queued:
            if item.drive_file_id not in active_drive_ids:
                self.update_video_status(
                    item.id,
                    VideoQueueStatus.SKIPPED,
                    error_message="Datei im Google Drive Staging-Ordner nicht mehr vorhanden.",
                )
                skipped_count += 1
        return skipped_count

    # --- Upload-Läufe & Einstellungen ---

    def record_upload_run(self, run: UploadRunRecord) -> None:
        self._executor.execute(
            """
            INSERT INTO upload_runs (
                run_id, started_at, finished_at, trigger_source, profile_name,
                dry_run, status, scanned_count, eligible_count, uploaded_count,
                skipped_count, failed_count, uploaded_video_ids_json, summary_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                finished_at = excluded.finished_at,
                status = excluded.status,
                scanned_count = excluded.scanned_count,
                eligible_count = excluded.eligible_count,
                uploaded_count = excluded.uploaded_count,
                skipped_count = excluded.skipped_count,
                failed_count = excluded.failed_count,
                uploaded_video_ids_json = excluded.uploaded_video_ids_json,
                summary_message = excluded.summary_message
            """,
            (
                run.run_id,
                run.started_at,
                run.finished_at,
                run.trigger_source.value,
                run.profile_name,
                1 if run.dry_run else 0,
                run.status.value,
                run.scanned_count,
                run.eligible_count,
                run.uploaded_count,
                run.skipped_count,
                run.failed_count,
                json.dumps(list(run.uploaded_video_ids)),
                run.summary_message,
            ),
        )

    def list_upload_runs(self, limit: int = 50) -> list[UploadRunRecord]:
        res = self._executor.execute(
            "SELECT * FROM upload_runs ORDER BY started_at DESC LIMIT ?",
            (int(limit),),
        )
        return [row_to_upload_run(row) for row in res.rows]

    def get_setting(self, key: str, default: str = "") -> str:
        res = self._executor.execute(
            "SELECT value FROM app_settings WHERE key = ? LIMIT 1",
            (key,),
        )
        return str(res.rows[0]["value"]) if res.rows else default

    def set_setting(self, key: str, value: str) -> None:
        self._executor.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, utc_now_iso()),
        )

    def load_runtime_settings(self, base: AppSettings) -> AppSettings:
        """Lädt nicht-geheime Laufzeiteinstellungen aus `app_settings` über `base`."""
        res = self._executor.execute("SELECT key, value FROM app_settings")
        if not res.rows:
            return base

        stored = {str(r["key"]): str(r["value"]) for r in res.rows}

        def _pick_str(key: str, fallback: str) -> str:
            return stored[key].strip() if key in stored else fallback

        def _pick_bool(key: str, fallback: bool) -> bool:
            if key not in stored:
                return fallback
            raw = stored[key].strip().lower()
            if raw in {"1", "true", "yes", "on"}:
                return True
            if raw in {"0", "false", "no", "off"}:
                return False
            return fallback

        def _pick_int(key: str, fallback: int) -> int:
            if key not in stored:
                return fallback
            try:
                return int(stored[key].strip())
            except ValueError:
                return fallback

        model = _pick_str("gemini_model", base.gemini_model)
        if base.allowed_models and model not in base.allowed_models:
            model = base.gemini_model

        provider = _pick_str("email_provider", base.email_provider).lower()
        if provider not in {"resend", "smtp"}:
            provider = base.email_provider

        return replace(
            base,
            gemini_model=model,
            drive_staging_folder_name=_pick_str(
                "drive_staging_folder_name", base.drive_staging_folder_name
            )
            or base.drive_staging_folder_name,
            drive_staging_folder_id=_pick_str(
                "drive_staging_folder_id", base.drive_staging_folder_id
            ),
            email_provider=provider,
            email_to=_pick_str("email_to", base.email_to),
            email_from=_pick_str("email_from", base.email_from) or base.email_from,
            smtp_host=_pick_str("smtp_host", base.smtp_host),
            smtp_port=_pick_int("smtp_port", base.smtp_port),
            smtp_user=_pick_str("smtp_user", base.smtp_user),
            notify_on_upload=_pick_bool("notify_on_upload", base.notify_on_upload),
            notify_on_error=_pick_bool("notify_on_error", base.notify_on_error),
            notify_on_empty_queue=_pick_bool("notify_on_empty_queue", base.notify_on_empty_queue),
            streamlit_app_url=_pick_str("streamlit_app_url", base.streamlit_app_url),
            github_repo=_pick_str("github_repo", base.github_repo),
            github_branch=_pick_str("github_branch", base.github_branch) or base.github_branch,
            github_workflow_file=_pick_str("github_workflow_file", base.github_workflow_file)
            or base.github_workflow_file,
        )

    def save_runtime_settings(self, updates: Mapping[str, str]) -> None:
        """Speichert nicht-geheime Laufzeiteinstellungen gebündelt in `app_settings`."""
        if not updates:
            return
        now = utc_now_iso()
        statements = [
            (
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (str(key), str(value), now),
            )
            for key, value in updates.items()
        ]
        self._executor.execute_batch(statements)

    # --- Google OAuth Konten & PKCE-States ---

    def create_oauth_state(
        self,
        *,
        state: str,
        code_verifier: str,
        redirect_uri: str,
        ttl_seconds: int = OAUTH_STATE_TTL_SECONDS,
        initiated_by_admin: bool = True,
    ) -> None:
        now_dt = datetime.now(UTC).replace(microsecond=0)
        expires_dt = now_dt + timedelta(seconds=max(60, int(ttl_seconds)))
        now_iso = now_dt.isoformat()
        self._executor.execute_batch(
            [
                ("DELETE FROM oauth_states WHERE expires_at <= ?", (now_iso,)),
                (
                    """
                    INSERT INTO oauth_states (
                        state, code_verifier, redirect_uri, initiated_by_admin, created_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        state,
                        code_verifier,
                        redirect_uri,
                        1 if initiated_by_admin else 0,
                        now_iso,
                        expires_dt.isoformat(),
                    ),
                ),
            ]
        )

    def consume_oauth_state(self, state: str) -> OAuthStateRecord | None:
        """Liest und löscht einen OAuth-State atomar (Einmal-Verwendung gegen Replay)."""
        clean_state = state.strip()
        if not clean_state:
            return None
        res = self._executor.execute(
            "SELECT * FROM oauth_states WHERE state = ? LIMIT 1",
            (clean_state,),
        )
        if not res.rows:
            return None
        record = row_to_oauth_state(res.rows[0])
        del_res = self._executor.execute(
            "DELETE FROM oauth_states WHERE state = ?",
            (clean_state,),
        )
        if del_res.affected_rows != 1:
            return None
        if record.expires_at <= utc_now_iso():
            return None
        return record

    def upsert_google_account(
        self,
        account: GoogleAccountRecord,
        *,
        set_active: bool = True,
    ) -> None:
        now = utc_now_iso()
        statements: list[tuple[str, Sequence[object]]] = []
        if set_active:
            statements.append(("UPDATE google_accounts SET is_active = 0 WHERE is_active = 1", ()))
        statements.append(
            (
                """
                INSERT INTO google_accounts (
                    account_id, email, display_name, youtube_channel_id,
                    youtube_channel_title, encrypted_refresh_token, scopes_json,
                    is_active, connected_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    email = excluded.email,
                    display_name = excluded.display_name,
                    youtube_channel_id = excluded.youtube_channel_id,
                    youtube_channel_title = excluded.youtube_channel_title,
                    encrypted_refresh_token = excluded.encrypted_refresh_token,
                    scopes_json = excluded.scopes_json,
                    is_active = excluded.is_active,
                    updated_at = excluded.updated_at
                """,
                (
                    account.account_id,
                    account.email,
                    account.display_name,
                    account.youtube_channel_id,
                    account.youtube_channel_title,
                    account.encrypted_refresh_token,
                    json.dumps(list(account.scopes)),
                    1 if (set_active or account.is_active) else 0,
                    account.connected_at or now,
                    now,
                ),
            )
        )
        self._executor.execute_batch(statements)

    def list_google_accounts(self) -> list[GoogleAccountRecord]:
        res = self._executor.execute(
            "SELECT * FROM google_accounts ORDER BY is_active DESC, updated_at DESC"
        )
        return [row_to_google_account(row) for row in res.rows]

    def get_active_google_account(self) -> GoogleAccountRecord | None:
        res = self._executor.execute(
            "SELECT * FROM google_accounts WHERE is_active = 1 ORDER BY updated_at DESC LIMIT 1"
        )
        if res.rows:
            return row_to_google_account(res.rows[0])
        fallback = self._executor.execute(
            "SELECT * FROM google_accounts ORDER BY updated_at DESC LIMIT 1"
        )
        return row_to_google_account(fallback.rows[0]) if fallback.rows else None

    def get_google_account(self, account_id: str) -> GoogleAccountRecord | None:
        res = self._executor.execute(
            "SELECT * FROM google_accounts WHERE account_id = ? LIMIT 1",
            (account_id.strip(),),
        )
        return row_to_google_account(res.rows[0]) if res.rows else None

    def set_active_google_account(self, account_id: str) -> bool:
        target = self.get_google_account(account_id)
        if target is None:
            return False
        now = utc_now_iso()
        self._executor.execute_batch(
            [
                ("UPDATE google_accounts SET is_active = 0 WHERE is_active = 1", ()),
                (
                    "UPDATE google_accounts SET is_active = 1, updated_at = ? WHERE account_id = ?",
                    (now, target.account_id),
                ),
            ]
        )
        return True

    def delete_google_account(self, account_id: str) -> None:
        clean_id = account_id.strip()
        if not clean_id:
            return
        self._executor.execute("DELETE FROM google_accounts WHERE account_id = ?", (clean_id,))
        if self.get_active_google_account() is None:
            return
        remaining = self.list_google_accounts()
        if remaining and not any(acc.is_active for acc in remaining):
            self.set_active_google_account(remaining[0].account_id)


def create_repository(settings: AppSettings) -> SqlBotRepository:
    """Erstellt ein Repository mit Turso (wenn konfiguriert) oder lokalem SQLite."""
    executor: SqlExecutor
    if settings.has_turso_configured:
        executor = TursoExecutor(settings.turso_url, settings.turso_key)
    else:
        executor = SqliteExecutor(settings.local_db_path)

    repo = SqlBotRepository(executor)
    if settings.default_profiles:
        repo.seed_default_profiles(settings.default_profiles)
    return repo
