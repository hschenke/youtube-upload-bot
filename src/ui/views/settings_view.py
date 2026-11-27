"""View 5: Google Web-OAuth-Login, Datenbank-Einstellungen, Secrets-Check & Test-E-Mail."""

from __future__ import annotations

import streamlit as st

from src.config.settings import AppSettings
from src.domain.exceptions import BotError
from src.integrations.drive_staging import GoogleDriveStagingClient
from src.integrations.youtube_uploader import YouTubeUploaderClient
from src.notifications.email_channel import EmailNotificationChannel
from src.security.google_oauth import GoogleOAuthCredentialProvider, GoogleWebOAuthFlow
from src.storage.repository import SqlBotRepository

_DEFAULT_LOCAL_REDIRECT = "http://localhost:8501"
_OAUTH_LINK_KEY = "ytbot_pending_google_auth_url"


def _render_google_accounts_section(settings: AppSettings, repository: SqlBotRepository) -> None:
    st.subheader("1. Google-Konten (Web-OAuth-Login)")
    st.caption(
        "Melde beliebige Google-Konten direkt im Browser an. Das aktive Konto wird für "
        "Google Fotos Picker, Google Drive Staging und den YouTube-Upload verwendet."
    )

    accounts = repository.list_google_accounts()
    if not accounts:
        st.info("Noch kein Google-Konto in der Datenbank verbunden.")
    else:
        for acc in accounts:
            badge = "🟢 Aktiv" if acc.is_active else "⚪ Bereit"
            channel = acc.youtube_channel_title or "YouTube-Kanal nicht erkannt"
            col_info, col_activate, col_remove = st.columns([3.2, 1.1, 1.0])
            col_info.markdown(f"**{badge}** • **{acc.email}**  \n📺 {channel}")
            if not acc.is_active and col_activate.button(
                "Als aktiv setzen", key=f"activate_{acc.account_id}", use_container_width=True
            ):
                repository.set_active_google_account(acc.account_id)
                st.rerun()
            if col_remove.button("Trennen", key=f"disconnect_{acc.account_id}", use_container_width=True):
                GoogleWebOAuthFlow(settings).disconnect_account(acc, repository)
                st.success(f"Konto '{acc.email}' getrennt.")
                st.rerun()

    redirect_default = settings.streamlit_app_url.strip() or _DEFAULT_LOCAL_REDIRECT
    col_redir, col_btn = st.columns([2.5, 1.5])
    redirect_uri = col_redir.text_input(
        "OAuth Redirect-URI (muss in Google Cloud Console eingetragen sein)",
        value=redirect_default,
    )
    with col_btn:
        st.write("")
        st.write("")
        if st.button("🔗 Neues Google-Konto verbinden", type="primary", use_container_width=True):
            try:
                auth_url, _ = GoogleWebOAuthFlow(settings).build_authorization_url(
                    redirect_uri=redirect_uri,
                    repository=repository,
                    initiated_by_admin=True,
                )
                st.session_state[_OAUTH_LINK_KEY] = auth_url
            except BotError as exc:
                st.error(str(exc))

    pending_url = st.session_state.get(_OAUTH_LINK_KEY)
    if pending_url:
        st.link_button("👉 Jetzt bei Google anmelden", pending_url, type="primary")
        st.caption("Nach der Bestätigung bei Google wirst du automatisch hierher zurückgeleitet.")

    if st.button("🔌 Aktives Google-Konto (Drive & YouTube) live testen"):
        creds = GoogleOAuthCredentialProvider(settings, repository=repository)
        if not creds.has_connected_account():
            st.error("Kein aktives Google-Konto verbunden oder OAUTH_ENCRYPTION_KEY fehlt.")
        else:
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
                    st.warning("Kein YouTube-Kanal für das aktive Google-Konto gefunden.")
            except BotError as exc:
                st.error(f"Verbindungstest fehlgeschlagen: {exc}")


def _render_runtime_settings_section(settings: AppSettings, repository: SqlBotRepository) -> None:
    st.subheader("2. Einstellungen in der Datenbank (keine Secrets)")
    st.caption(
        "Diese Werte sind keine Passwörter und werden zentral in SQLite/Turso gespeichert – "
        "Web-App und GitHub Actions lesen automatisch denselben Stand."
    )

    models = list(settings.allowed_models)
    model_idx = models.index(settings.gemini_model) if settings.gemini_model in models else 0
    providers = ["resend", "smtp"]
    prov_idx = providers.index(settings.email_provider) if settings.email_provider in providers else 0

    with st.form("runtime_settings_form"):
        c1, c2, c3 = st.columns(3)
        gemini_model = c1.selectbox("Gemini Modell", options=models, index=model_idx)
        staging_name = c2.text_input(
            "Drive Staging-Ordnername", value=settings.drive_staging_folder_name
        )
        staging_id = c3.text_input(
            "Drive Staging-Ordner-ID (optional)", value=settings.drive_staging_folder_id
        )

        c4, c5, c6 = st.columns(3)
        email_provider = c4.selectbox("E-Mail-Provider", options=providers, index=prov_idx)
        email_to = c5.text_input("Empfänger-E-Mail (`EMAIL_TO`)", value=settings.email_to)
        email_from = c6.text_input("Absender (`EMAIL_FROM`)", value=settings.email_from)

        c7, c8, c9 = st.columns(3)
        notify_upload = c7.checkbox("Mail bei Upload", value=settings.notify_on_upload)
        notify_error = c8.checkbox("Mail bei Fehler", value=settings.notify_on_error)
        notify_empty = c9.checkbox("Mail bei leerer Queue", value=settings.notify_on_empty_queue)

        c10, c11 = st.columns(2)
        streamlit_url = c10.text_input(
            "Streamlit App-URL (Redirect & Mail-Link)", value=settings.streamlit_app_url
        )
        github_repo = c11.text_input("GitHub Repo (optional)", value=settings.github_repo)

        c12, c13 = st.columns(2)
        github_branch = c12.text_input("GitHub Branch", value=settings.github_branch)
        github_workflow = c13.text_input(
            "GitHub Workflow-Datei", value=settings.github_workflow_file
        )

        if st.form_submit_button("💾 Einstellungen in Datenbank speichern", type="primary"):
            repository.save_runtime_settings(
                {
                    "gemini_model": gemini_model,
                    "drive_staging_folder_name": staging_name.strip() or "youtube-upload-bot-staging",
                    "drive_staging_folder_id": staging_id.strip(),
                    "email_provider": email_provider,
                    "email_to": email_to.strip(),
                    "email_from": email_from.strip() or "YouTube Upload Bot <onboarding@resend.dev>",
                    "notify_on_upload": "true" if notify_upload else "false",
                    "notify_on_error": "true" if notify_error else "false",
                    "notify_on_empty_queue": "true" if notify_empty else "false",
                    "streamlit_app_url": streamlit_url.strip().rstrip("/"),
                    "github_repo": github_repo.strip(),
                    "github_branch": github_branch.strip() or "main",
                    "github_workflow_file": github_workflow.strip() or "upload_videos.yaml",
                }
            )
            st.success("Einstellungen gespeichert.")
            st.rerun()


def _render_secrets_and_mail_section(settings: AppSettings, repository: SqlBotRepository) -> None:
    st.subheader("3. Secrets-Status & Test-E-Mail")

    checks = [
        ("GOOGLE_CLIENT_ID / SECRET", settings.has_google_client_configured),
        ("OAUTH_ENCRYPTION_KEY", settings.has_oauth_encryption_configured),
        ("GEMINI_API_KEY", settings.has_gemini_configured),
        ("TURSO_URL / TURSO_KEY", settings.has_turso_configured),
        ("RESEND_API_KEY", bool(settings.resend_api_key)),
        ("APP_PASSWORD", bool(settings.app_password)),
    ]
    cols = st.columns(3)
    for idx, (label, ok) in enumerate(checks):
        cols[idx % 3].metric(label, "✅ gesetzt" if ok else "❌ fehlt")

    notifier = EmailNotificationChannel(settings)
    with st.form("test_email_form"):
        recipient = st.text_input("Test-Empfänger (leer = gespeicherte EMAIL_TO)")
        if st.form_submit_button("✉️ Test-E-Mail senden"):
            ok, msg = notifier.send_test_email(recipient)
            if ok:
                st.success(msg)
            else:
                st.error(msg)

    st.caption(f"Aktives DB-Backend: `{repository.backend_name}`")


def render_settings_view(settings: AppSettings, repository: SqlBotRepository) -> None:
    st.header("⚙️ System & Setup")
    _render_google_accounts_section(settings, repository)
    st.divider()
    _render_runtime_settings_section(settings, repository)
    st.divider()
    _render_secrets_and_mail_section(settings, repository)
