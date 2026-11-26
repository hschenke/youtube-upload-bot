"""Typisierte Anwendungskonfiguration aus YAML, Umgebungsvariablen und Streamlit Secrets."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from src.config.constants import (
    CANDIDATE_MODELS,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_LOCAL_DB_PATH,
    DEFAULT_SETTINGS_YAML_PATH,
    DEFAULT_SMTP_PORT,
    DEFAULT_STAGING_FOLDER_NAME,
)
from src.domain.enums import PrivacyStatus, SelectionOrder, VideoOrientation
from src.domain.models import UploadProfile


def _read_streamlit_secrets() -> dict[str, Any]:
    """Liest optional `st.secrets`, ohne im reinen CLI-Worker Streamlit vorauszusetzen."""
    try:
        import streamlit as st

        return dict(st.secrets)
    except Exception:
        return {}


def _get_config_value(
    key: str,
    secrets_map: Mapping[str, Any],
    default: str = "",
) -> str:
    env_val = os.getenv(key)
    if env_val is not None and env_val.strip():
        return env_val.strip()
    secret_val = secrets_map.get(key)
    if secret_val is not None and str(secret_val).strip():
        return str(secret_val).strip()
    return default


def _parse_int(raw: str, default: int) -> int:
    try:
        return int(raw.strip())
    except (ValueError, AttributeError):
        return default


def _parse_bool(raw: Any, default: bool) -> bool:
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return default
    lowered = str(raw).strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return default


def _load_yaml_settings(yaml_path: Path) -> dict[str, Any]:
    if not yaml_path.exists():
        return {}
    with yaml_path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    return loaded if isinstance(loaded, dict) else {}


def _parse_default_profiles(yaml_data: dict[str, Any]) -> tuple[UploadProfile, ...]:
    raw_profiles = yaml_data.get("profiles")
    if not isinstance(raw_profiles, dict):
        return ()

    parsed: list[UploadProfile] = []
    for name, cfg in raw_profiles.items():
        if not isinstance(cfg, dict):
            continue
        parsed.append(
            UploadProfile(
                name=str(name).strip().lower(),
                display_name=str(cfg.get("display_name") or name).strip(),
                enabled=bool(cfg.get("enabled", True)),
                orientation=VideoOrientation(str(cfg.get("orientation", "portrait"))),
                min_aspect_ratio=cfg.get("min_aspect_ratio"),
                max_aspect_ratio=cfg.get("max_aspect_ratio"),
                min_duration_seconds=cfg.get("min_duration_seconds"),
                max_duration_seconds=cfg.get("max_duration_seconds"),
                min_width=cfg.get("min_width"),
                min_height=cfg.get("min_height"),
                date_from=cfg.get("date_from"),
                date_to=cfg.get("date_to"),
                include_filename_patterns=tuple(
                    str(p).strip() for p in (cfg.get("include_filename_patterns") or []) if str(p).strip()
                ),
                exclude_filename_patterns=tuple(
                    str(p).strip() for p in (cfg.get("exclude_filename_patterns") or []) if str(p).strip()
                ),
                selection_order=SelectionOrder(str(cfg.get("selection_order", "oldest_first"))),
                max_uploads_per_run=int(cfg.get("max_uploads_per_run", 1)),
                privacy_status=PrivacyStatus(str(cfg.get("privacy_status", "public"))),
                category_id=str(cfg.get("category_id", "22")),
                made_for_kids=bool(cfg.get("made_for_kids", False)),
                language=str(cfg.get("language", "en")),
                required_hashtags=tuple(
                    str(h).strip() for h in (cfg.get("required_hashtags") or []) if str(h).strip()
                ),
                default_tags=tuple(
                    str(t).strip() for t in (cfg.get("default_tags") or []) if str(t).strip()
                ),
                description_footer=str(cfg.get("description_footer") or ""),
                ai_prompt=str(cfg.get("ai_prompt") or ""),
            )
        )
    return tuple(parsed)


@dataclass(frozen=True)
class AppSettings:
    """Unveränderliche Laufzeitkonfiguration für Worker und Streamlit-Dashboard."""

    google_client_id: str = ""
    google_client_secret: str = ""
    google_refresh_token: str = ""
    drive_staging_folder_id: str = ""
    drive_staging_folder_name: str = DEFAULT_STAGING_FOLDER_NAME
    gemini_api_key: str = ""
    gemini_model: str = DEFAULT_GEMINI_MODEL
    allowed_models: tuple[str, ...] = CANDIDATE_MODELS
    turso_url: str = ""
    turso_key: str = ""
    local_db_path: str = DEFAULT_LOCAL_DB_PATH
    app_password: str = ""
    email_provider: str = "resend"
    resend_api_key: str = ""
    email_to: str = ""
    email_from: str = "YouTube Upload Bot <onboarding@resend.dev>"
    smtp_host: str = ""
    smtp_port: int = DEFAULT_SMTP_PORT
    smtp_user: str = ""
    smtp_pass: str = ""
    notify_on_upload: bool = True
    notify_on_error: bool = True
    notify_on_empty_queue: bool = True
    github_token: str = ""
    github_repo: str = ""
    github_branch: str = "main"
    github_workflow_file: str = "upload_videos.yaml"
    streamlit_app_url: str = ""
    default_profiles: tuple[UploadProfile, ...] = field(default_factory=tuple)

    @property
    def has_google_oauth_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret and self.google_refresh_token)

    @property
    def has_gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def has_turso_configured(self) -> bool:
        return bool(self.turso_url and self.turso_key)

    @property
    def has_email_configured(self) -> bool:
        if self.email_provider == "smtp":
            return bool(self.smtp_host and self.smtp_user and self.smtp_pass and self.email_to)
        return bool(self.resend_api_key and self.email_to)

    @property
    def has_github_worker_configured(self) -> bool:
        return bool(self.github_token and self.github_repo)


def load_app_settings(
    yaml_path: str | Path = DEFAULT_SETTINGS_YAML_PATH,
    dotenv_path: str | Path | None = ".env",
) -> AppSettings:
    """Lädt Konfiguration aus `.env`, `settings.yaml`, Umgebung und `st.secrets`."""
    if dotenv_path is not None:
        load_dotenv(dotenv_path=dotenv_path, override=False)

    yaml_data = _load_yaml_settings(Path(yaml_path))
    secrets_map = _read_streamlit_secrets()

    raw_models = yaml_data.get("allowed_models")
    allowed_models = (
        tuple(str(m).strip() for m in raw_models if str(m).strip())
        if isinstance(raw_models, list) and raw_models
        else CANDIDATE_MODELS
    )

    notif_cfg = yaml_data.get("notifications")
    notif_dict = notif_cfg if isinstance(notif_cfg, dict) else {}

    folder_name = _get_config_value(
        "GOOGLE_DRIVE_STAGING_FOLDER_NAME",
        secrets_map,
        str(yaml_data.get("staging_folder_name") or DEFAULT_STAGING_FOLDER_NAME),
    )

    gemini_model = _get_config_value("GEMINI_MODEL", secrets_map, DEFAULT_GEMINI_MODEL)
    if gemini_model not in allowed_models:
        gemini_model = allowed_models[0]

    return AppSettings(
        google_client_id=_get_config_value("GOOGLE_CLIENT_ID", secrets_map),
        google_client_secret=_get_config_value("GOOGLE_CLIENT_SECRET", secrets_map),
        google_refresh_token=_get_config_value("GOOGLE_REFRESH_TOKEN", secrets_map),
        drive_staging_folder_id=_get_config_value("GOOGLE_DRIVE_STAGING_FOLDER_ID", secrets_map),
        drive_staging_folder_name=folder_name,
        gemini_api_key=_get_config_value("GEMINI_API_KEY", secrets_map),
        gemini_model=gemini_model,
        allowed_models=allowed_models,
        turso_url=_get_config_value("TURSO_URL", secrets_map),
        turso_key=_get_config_value("TURSO_KEY", secrets_map),
        local_db_path=_get_config_value("LOCAL_DB_PATH", secrets_map, DEFAULT_LOCAL_DB_PATH),
        app_password=_get_config_value("APP_PASSWORD", secrets_map),
        email_provider=_get_config_value("EMAIL_PROVIDER", secrets_map, "resend").lower(),
        resend_api_key=_get_config_value("RESEND_API_KEY", secrets_map),
        email_to=_get_config_value("EMAIL_TO", secrets_map),
        email_from=_get_config_value(
            "EMAIL_FROM", secrets_map, "YouTube Upload Bot <onboarding@resend.dev>"
        ),
        smtp_host=_get_config_value("SMTP_HOST", secrets_map),
        smtp_port=_parse_int(_get_config_value("SMTP_PORT", secrets_map), DEFAULT_SMTP_PORT),
        smtp_user=_get_config_value("SMTP_USER", secrets_map),
        smtp_pass=_get_config_value("SMTP_PASS", secrets_map),
        notify_on_upload=_parse_bool(
            _get_config_value("NOTIFY_ON_UPLOAD", secrets_map) or notif_dict.get("notify_on_upload"),
            True,
        ),
        notify_on_error=_parse_bool(
            _get_config_value("NOTIFY_ON_ERROR", secrets_map) or notif_dict.get("notify_on_error"),
            True,
        ),
        notify_on_empty_queue=_parse_bool(
            _get_config_value("NOTIFY_ON_EMPTY_QUEUE", secrets_map)
            or notif_dict.get("notify_on_empty_queue"),
            True,
        ),
        github_token=_get_config_value("GITHUB_TOKEN", secrets_map),
        github_repo=_get_config_value("GITHUB_REPO", secrets_map),
        github_branch=_get_config_value("GITHUB_BRANCH", secrets_map, "main"),
        github_workflow_file=_get_config_value(
            "GITHUB_WORKFLOW_FILE", secrets_map, "upload_videos.yaml"
        ),
        streamlit_app_url=_get_config_value("STREAMLIT_APP_URL", secrets_map),
        default_profiles=_parse_default_profiles(yaml_data),
    )
