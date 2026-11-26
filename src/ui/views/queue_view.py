"""View 2: Video-Queue, Filter-Treffer, manuelle Overrides & Sofort-Run."""

from __future__ import annotations

import streamlit as st

from src.config.settings import AppSettings
from src.domain.enums import TriggerSource, VideoQueueStatus
from src.domain.exceptions import BotError
from src.domain.models import UploadProfile, VideoQueueItem
from src.domain.schemas import normalize_hashtag
from src.media.filter_engine import evaluate_video_for_profile
from src.storage.repository import SqlBotRepository
from src.ui.formatters import (
    format_bytes,
    format_duration,
    format_resolution,
    format_status_badge,
)
from src.worker.github_dispatcher import GitHubActionsDispatcher
from src.worker.pipeline import UploadPipelineService


def _render_top_actions(
    settings: AppSettings,
    repository: SqlBotRepository,
    profiles: list[UploadProfile],
) -> None:
    col1, col2, col3, col4 = st.columns([1.2, 1.2, 1.2, 1.4])
    with col1:
        if st.button("🔄 Drive-Ordner syncen", use_container_width=True):
            try:
                pipeline = UploadPipelineService(settings, repository)
                scanned, missing = pipeline.sync_drive_queue()
                st.success(f"Sync OK: {scanned} in Drive, {missing} fehlende übersprungen.")
                st.rerun()
            except BotError as exc:
                st.error(f"Sync fehlgeschlagen: {exc}")

    profile_names = [p.name for p in profiles]
    with col2:
        chosen_profile = st.selectbox(
            "Profil für Lauf",
            options=["", *profile_names],
            format_func=lambda x: "Alle aktiven Profile" if x == "" else x,
        )
    with col3:
        dry_run = st.checkbox("Dry-Run (nur Simulation)", value=True)
    with col4:
        if st.button("🚀 GitHub-Worker jetzt starten", type="primary", use_container_width=True):
            try:
                GitHubActionsDispatcher(settings).trigger_upload_run(
                    profile=chosen_profile,
                    dry_run=dry_run,
                )
                st.success("GitHub Actions Workflow gestartet!")
            except BotError as exc:
                st.error(f"Workflow-Start fehlgeschlagen: {exc}")

    if st.button("▶️ Lokal im Dashboard ausführen", use_container_width=False):
        with st.spinner("Pipeline läuft..."):
            pipeline = UploadPipelineService(settings, repository)
            run = pipeline.run_scheduled_upload(
                profile_name=chosen_profile,
                dry_run=dry_run,
                trigger_source=TriggerSource.STREAMLIT,
            )
        st.info(f"Run `{run.run_id}` ({run.status.value}): {run.summary_message}")


def _render_video_card(
    video: VideoQueueItem,
    active_profile: UploadProfile | None,
    repository: SqlBotRepository,
) -> None:
    eval_text = ""
    if active_profile is not None:
        evaluation = evaluate_video_for_profile(video, active_profile)
        eval_text = "✅ passt" if evaluation.matched else f"⛔ {', '.join(evaluation.reasons)}"

    header = (
        f"{format_status_badge(video.status)} | **{video.filename}** "
        f"({format_resolution(video.width, video.height)}, {format_duration(video.duration_seconds)}, "
        f"{format_bytes(video.size_bytes)})"
    )
    with st.expander(header):
        st.caption(
            f"ID: `{video.id}` • Drive: `{video.drive_file_id}` • "
            f"Aufnahme: `{video.recorded_at or 'unbekannt'}`"
        )
        if eval_text:
            st.write(f"**Profil-Check ({active_profile.name if active_profile else '-'}):** {eval_text}")
        if video.error_message:
            st.warning(f"Hinweis/Fehler: {video.error_message}")

        with st.form(f"override_form_{video.id}"):
            title_ov = st.text_input("Manueller Titel (optional)", value=video.title_override or "")
            desc_ov = st.text_area(
                "Manuelle Beschreibung (optional)",
                value=video.description_override or "",
                height=80,
            )
            tags_ov = st.text_input(
                "Manuelle Hashtags (kommagetrennt, optional)",
                value=", ".join(video.hashtags_override),
            )
            col_save, col_skip, col_requeue = st.columns(3)
            save_clicked = col_save.form_submit_button("💾 Overrides speichern")
            skip_clicked = col_skip.form_submit_button("⏭️ Überspringen")
            requeue_clicked = col_requeue.form_submit_button("🔁 Zurück in Queue")

        if save_clicked:
            parsed_tags = [
                norm
                for raw in tags_ov.split(",")
                if (norm := normalize_hashtag(raw))
            ]
            repository.update_manual_metadata(
                video.id,
                title_override=title_ov.strip() or None,
                description_override=desc_ov.strip() or None,
                hashtags_override=parsed_tags,
            )
            st.success("Metadaten-Overrides gespeichert.")
            st.rerun()
        elif skip_clicked:
            repository.update_video_status(video.id, VideoQueueStatus.SKIPPED)
            st.rerun()
        elif requeue_clicked:
            repository.update_video_status(video.id, VideoQueueStatus.QUEUED, error_message=None)
            st.rerun()


def render_queue_view(settings: AppSettings, repository: SqlBotRepository) -> None:
    st.header("🎬 Video-Queue & Filter-Vorschau")
    profiles = repository.list_profiles()
    _render_top_actions(settings, repository, profiles)
    st.divider()

    col_f1, col_f2 = st.columns(2)
    status_filter = col_f1.selectbox(
        "Status-Filter",
        options=["alle", *(s.value for s in VideoQueueStatus)],
    )
    preview_profile_name = col_f2.selectbox(
        "Filter-Vorschau gegen Profil",
        options=[p.name for p in profiles] if profiles else [""],
    )
    active_profile = repository.get_profile(preview_profile_name) if preview_profile_name else None

    target_status = None if status_filter == "alle" else VideoQueueStatus(status_filter)
    videos = repository.list_videos(status=target_status, limit=200)
    if not videos:
        st.info("Keine Videos für diesen Filter in der Queue.")
        return

    for video in videos:
        _render_video_card(video, active_profile, repository)
