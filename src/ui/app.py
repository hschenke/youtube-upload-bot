"""Haupt-Controller der Streamlit Web-App (reine Präsentationsschicht)."""

from __future__ import annotations

import streamlit as st

from src.__version__ import __version__
from src.config.settings import AppSettings, load_app_settings
from src.domain.enums import AuthRole
from src.domain.exceptions import GoogleAuthError
from src.security.auth import generate_admin_token
from src.security.google_oauth import GoogleOAuthCredentialProvider, GoogleWebOAuthFlow
from src.storage.repository import SqlBotRepository, create_repository
from src.ui.auth_view import enforce_authentication
from src.ui.styles import inject_global_styles
from src.ui.views.history_view import render_history_view
from src.ui.views.picker_import_view import render_picker_import_view
from src.ui.views.profiles_view import render_profiles_view
from src.ui.views.queue_view import render_queue_view
from src.ui.views.settings_view import render_settings_view

_SESSION_TOKEN_KEY = "ytbot_auth_token"  # noqa: S105
_OAUTH_FLASH_KEY = "ytbot_oauth_flash"


def _handle_google_oauth_callback(settings: AppSettings, repository: SqlBotRepository) -> None:
    """Verarbeitet Google-OAuth-Redirects (`?code=...&state=...`) vor dem Login-Gate."""
    if "error" in st.query_params and "state" in st.query_params:
        err = str(st.query_params.get("error") or "access_denied")
        st.query_params.clear()
        st.session_state[_OAUTH_FLASH_KEY] = ("error", f"Google-Anmeldung abgebrochen: {err}")
        st.rerun()

    code = str(st.query_params.get("code") or "").strip()
    state = str(st.query_params.get("state") or "").strip()
    if not code or not state:
        return

    try:
        account, initiated_by_admin = GoogleWebOAuthFlow(settings).handle_callback(
            code=code,
            state=state,
            repository=repository,
        )
        if initiated_by_admin and settings.app_password.strip():
            st.session_state[_SESSION_TOKEN_KEY] = generate_admin_token(settings.app_password)
        channel_hint = f" (Kanal: {account.youtube_channel_title})" if account.youtube_channel_title else ""
        st.session_state[_OAUTH_FLASH_KEY] = (
            "success",
            f"Google-Konto **{account.email}** erfolgreich verbunden{channel_hint}.",
        )
    except GoogleAuthError as exc:
        st.session_state[_OAUTH_FLASH_KEY] = ("error", f"Google-Login fehlgeschlagen: {exc}")
    finally:
        st.query_params.clear()
    st.rerun()


def run_streamlit_app() -> None:
    """Initialisiert Seite, OAuth-Callback, Authentifizierung, Navigation und Teilansicht."""
    st.set_page_config(
        page_title="YouTube-Upload-Bot",
        page_icon="🎬",
        layout="wide",
    )
    inject_global_styles()

    base_settings = load_app_settings()
    repository = create_repository(base_settings)

    try:
        settings = repository.load_runtime_settings(base_settings)
        _handle_google_oauth_callback(settings, repository)
        role = enforce_authentication(settings)

        flash = st.session_state.pop(_OAUTH_FLASH_KEY, None)
        if isinstance(flash, tuple) and len(flash) == 2:
            level, msg = flash
            if level == "success":
                st.success(msg)
            else:
                st.error(msg)

        active_account = repository.get_active_google_account()
        creds = GoogleOAuthCredentialProvider(settings, repository=repository)

        with st.sidebar:
            st.title("🎬 YouTube-Upload-Bot")
            st.caption(f"v{__version__} • Photos → Drive → YouTube")
            if role == AuthRole.READONLY:
                st.info("🔓 Lese-Ansicht (E-Mail-Direktlink)")
                selected_page = "📺 Upload-Historie"
            else:
                default_view = str(st.query_params.get("view", "")).strip()
                pages = [
                    "📸 Google Fotos Import",
                    "🎬 Video-Queue",
                    "🎛️ Profile & Prompts",
                    "📺 Upload-Historie",
                    "⚙️ System & Setup",
                ]
                default_idx = 3 if default_view == "history" else 0
                selected_page = st.radio("Navigation", options=pages, index=default_idx)

            st.divider()
            if active_account is not None and creds.has_connected_account():
                channel_label = active_account.youtube_channel_title or "Kein Kanal gefunden"
                st.caption(f"✅ Google: **{active_account.email}**\n\n📺 {channel_label}")
            elif creds.has_connected_account():
                st.caption("✅ Google: **OAuth Fallback (.env)**")
            else:
                st.caption("⚠️ **Kein Google-Konto verbunden** → Setup")

            st.caption(f"Datenbank: **{repository.backend_name}**")
            if st.button("🔄 Ansicht aktualisieren", use_container_width=True):
                st.rerun()

        if selected_page == "📸 Google Fotos Import":
            render_picker_import_view(settings, repository)
        elif selected_page == "🎬 Video-Queue":
            render_queue_view(settings, repository)
        elif selected_page == "🎛️ Profile & Prompts":
            render_profiles_view(settings, repository)
        elif selected_page == "📺 Upload-Historie":
            render_history_view(repository)
        else:
            render_settings_view(settings, repository)
    finally:
        repository.close()
