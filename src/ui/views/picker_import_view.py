"""View 1: Google Photos Picker Ingest & alternativer direkter Video-Upload nach Drive."""

from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st

from src.config.settings import AppSettings
from src.domain.exceptions import BotError
from src.integrations.drive_staging import GoogleDriveStagingClient
from src.integrations.photos_picker import GooglePhotosPickerClient
from src.media.probe import compute_file_sha256, probe_video_file
from src.security.google_oauth import GoogleOAuthCredentialProvider
from src.security.sanitization import get_safe_filepath, sanitize_display_url, sanitize_filename
from src.storage.repository import SqlBotRepository
from src.worker.pipeline import UploadPipelineService

_PICKER_SESSION_KEY = "ytbot_picker_session"


def _render_picker_section(settings: AppSettings, repository: SqlBotRepository) -> None:
    st.subheader("1. Aus Google Fotos auswählen (Picker API)")
    st.write(
        "Starte eine sichere Google-Photos-Auswahl. Ausgewählte Videos werden sofort in deinen "
        "Google Drive Staging-Ordner übertragen, damit der GitHub-Actions-Bot sie automatisch nach Zeitplan hochladen kann."
    )

    if not settings.has_google_oauth_configured:
        st.warning(
            "Google OAuth ist noch nicht konfiguriert. Bitte zuerst unter **⚙️ System & Setup** "
            "oder in `.env` / Secrets hinterlegen."
        )
        return

    creds = GoogleOAuthCredentialProvider(settings)
    picker = GooglePhotosPickerClient(creds)

    col_a, col_b = st.columns([1, 2])
    with col_a:
        max_items = st.number_input("Max. Videos pro Auswahl", min_value=1, max_value=100, value=25)
        if st.button("📸 Google Photos Picker starten", type="primary", use_container_width=True):
            try:
                session_info = picker.create_session(max_item_count=int(max_items))
                st.session_state[_PICKER_SESSION_KEY] = session_info
            except BotError as exc:
                st.error(f"Picker-Session konnte nicht gestartet werden: {exc}")

    session_info = st.session_state.get(_PICKER_SESSION_KEY)
    with col_b:
        if session_info is not None:
            safe_uri = sanitize_display_url(session_info.picker_uri)
            st.success(f"Picker-Session aktiv: `{session_info.session_id}`")
            st.link_button("🔗 Google Fotos öffnen & Videos wählen", safe_uri, type="secondary")
            st.caption(
                "Nachdem du in Google Fotos auf **Fertig** geklickt hast, starte unten den Import."
            )

            if st.button("⬇️ Auswahl prüfen & in Drive-Queue übernehmen", type="primary"):
                _run_picker_import(settings, repository, picker, session_info.session_id)


def _run_picker_import(
    settings: AppSettings,
    repository: SqlBotRepository,
    picker: GooglePhotosPickerClient,
    session_id: str,
) -> None:
    try:
        status = picker.get_session(session_id)
        if not status.media_items_set:
            st.info(
                "In Google Fotos wurde die Auswahl noch nicht abgeschlossen (`mediaItemsSet = false`). "
                "Bitte erst dort Videos auswählen und bestätigen."
            )
            return

        with st.spinner("Videos werden von Google Fotos in den Drive Staging-Ordner übertragen..."):
            pipeline = UploadPipelineService(settings, repository, picker_client=picker)
            summary = pipeline.import_from_picker_session(session_id)

        st.session_state.pop(_PICKER_SESSION_KEY, None)
        st.success(
            f"Import abgeschlossen: {summary.imported_count} neu gestagt, "
            f"{summary.skipped_duplicates} Duplikate übersprungen, "
            f"{summary.failed_count} fehlgeschlagen (aus {summary.picked_videos} Videos)."
        )
    except BotError as exc:
        st.error(f"Import fehlgeschlagen: {exc}")


def _render_direct_upload_section(settings: AppSettings, repository: SqlBotRepository) -> None:
    st.subheader("2. Alternativ: Direktes Video in Drive-Staging hochladen")
    if not settings.has_google_oauth_configured:
        st.caption("Google OAuth erforderlich.")
        return

    uploaded_files = st.file_uploader(
        "MP4/MOV-Videos direkt hochladen",
        type=["mp4", "mov", "m4v", "webm"],
        accept_multiple_files=True,
    )
    if not uploaded_files:
        return

    if st.button("☁️ In Drive Staging-Ordner hochladen"):
        creds = GoogleOAuthCredentialProvider(settings)
        drive = GoogleDriveStagingClient(
            creds,
            folder_id=settings.drive_staging_folder_id,
            folder_name=settings.drive_staging_folder_name,
        )
        folder_id = drive.ensure_staging_folder()
        imported = 0
        for file_obj in uploaded_files:
            safe_name = sanitize_filename(file_obj.name)
            with tempfile.TemporaryDirectory(prefix="ytbot_direct_") as tmp_dir:
                target = get_safe_filepath(Path(tmp_dir), safe_name)
                target.write_bytes(file_obj.getbuffer())
                sha256_hex = compute_file_sha256(target)
                try:
                    probe_res = probe_video_file(target)
                except BotError:
                    probe_res = None
                drive_file = drive.upload_video_file(
                    target,
                    filename=safe_name,
                    mime_type=file_obj.type or "video/mp4",
                    folder_id=folder_id,
                    original_created_at=probe_res.creation_time if probe_res else None,
                )
                repository.upsert_staged_video(
                    drive_file,
                    width=probe_res.display_width if probe_res else None,
                    height=probe_res.display_height if probe_res else None,
                    duration_seconds=probe_res.duration_seconds if probe_res else None,
                    fps=probe_res.fps if probe_res else None,
                    content_sha256=sha256_hex,
                )
                imported += 1
        st.success(f"{imported} Video(s) erfolgreich in Drive gestagt.")


def render_picker_import_view(settings: AppSettings, repository: SqlBotRepository) -> None:
    st.header("📸 Google Fotos Import")
    _render_picker_section(settings, repository)
    st.divider()
    _render_direct_upload_section(settings, repository)
