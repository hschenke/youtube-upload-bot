"""Haupt-Controller der Streamlit Web-App (reine Präsentationsschicht)."""

from __future__ import annotations

import streamlit as st

from src.__version__ import __version__
from src.config.settings import load_app_settings
from src.domain.enums import AuthRole
from src.storage.repository import create_repository
from src.ui.auth_view import enforce_authentication
from src.ui.styles import inject_global_styles
from src.ui.views.history_view import render_history_view
from src.ui.views.picker_import_view import render_picker_import_view
from src.ui.views.profiles_view import render_profiles_view
from src.ui.views.queue_view import render_queue_view
from src.ui.views.settings_view import render_settings_view


def run_streamlit_app() -> None:
    """Initialisiert Seite, Authentifizierung, Navigation und gewählte Teilansicht."""
    st.set_page_config(
        page_title="YouTube-Upload-Bot",
        page_icon="🎬",
        layout="wide",
    )
    inject_global_styles()

    settings = load_app_settings()
    role = enforce_authentication(settings)
    repository = create_repository(settings)

    try:
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
