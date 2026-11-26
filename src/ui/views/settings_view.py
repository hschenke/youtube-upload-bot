"""View 5: Systemstatus, API-Checks, Benachrichtigungen und Setup-Hinweise."""

from __future__ import annotations

import streamlit as st

from src.config.settings import AppSettings
from src.domain.exceptions import BotError
from src.integrations.drive_staging import GoogleDriveStagingClient
from src.integrations.youtube_uploader import YouTubeUploaderClient
from src.notifications.email_channel import EmailNotificationChannel
from src.security.google_oauth import GoogleOAuthCredentialProvider
from src.storage.repository import SqlBotRepository


def render_settings_view(settings: AppSettings, repository: SqlBotRepository) -> None:
    st.header("⚙️ System & Setup")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Datenbank", "Turso Cloud" if settings.has_turso_configured else "SQLite lokal")
    col2.metric("Google OAuth", "Aktiv" if settings.has_google_oauth_configured else "Fehlt")
    col3.metric("Gemini API", settings.gemini_model if settings.has_gemini_configured else "Fehlt")
    col4.metric("E-Mail", settings.email_provider if settings.has_email_configured else "Aus")

    st.subheader("Live-Verbindungstest (Google Drive & YouTube)")
    if st.button("🔌 Google-APIs prüfen"):
        if not settings.has_google_oauth_configured:
            st.error("Google OAuth Zugangsdaten fehlen.")
        else:
            creds = GoogleOAuthCredentialProvider(settings)
            try:
                folder_id = GoogleDriveStagingClient(
                    creds,
                    folder_id=settings.drive_staging_folder_id,
                    folder_name=settings.drive_staging_folder_name,
                ).ensure_staging_folder()
                channel = YouTubeUploaderClient(creds).get_channel_info()
                st.success(f"Drive Staging-Ordner bereit (`{folder_id}`).")
                if channel:
                    st.success(
                        f"YouTube-Kanal verbunden: **{channel['title']}** "
                        f"({channel['video_count']} Videos)"
                    )
                else:
                    st.warning("Kein YouTube-Kanal für diesen Google-Account gefunden.")
            except BotError as exc:
                st.error(f"Verbindungsfehler: {exc}")

    st.divider()
    st.subheader("Benachrichtigungen & Test-E-Mail")
    st.write(
        f"- Bei erfolgreichem Upload: **{'Ja' if settings.notify_on_upload else 'Nein'}**\n"
        f"- Bei Fehlern: **{'Ja' if settings.notify_on_error else 'Nein'}**\n"
        f"- Bei leerer Queue: **{'Ja' if settings.notify_on_empty_queue else 'Nein'}**"
    )
    notifier = EmailNotificationChannel(settings)
    with st.form("test_email_form"):
        recipient = st.text_input("Test-Empfänger (leer = EMAIL_TO aus Secrets)")
        if st.form_submit_button("✉️ Test-E-Mail senden"):
            ok, msg = notifier.send_test_email(recipient)
            if ok:
                st.success(msg)
            else:
                st.error(msg)

    st.caption(f"Aktives DB-Backend: `{repository.backend_name}`")
