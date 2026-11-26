"""View 4: Hochgeladene YouTube-Videos und Protokoll der Bot-Läufe."""

from __future__ import annotations

import streamlit as st

from src.domain.enums import VideoQueueStatus
from src.security.sanitization import sanitize_display_url
from src.storage.repository import SqlBotRepository
from src.ui.formatters import format_duration, format_run_status_badge


def render_history_view(repository: SqlBotRepository) -> None:
    st.header("📺 Upload-Historie & Bot-Läufe")

    uploaded = repository.list_videos(status=VideoQueueStatus.UPLOADED, limit=100)
    st.subheader(f"Hochgeladene Videos ({len(uploaded)})")
    if not uploaded:
        st.info("Noch keine Videos über den Bot hochgeladen.")
    else:
        for item in uploaded:
            title = item.generated_title or item.title_override or item.filename
            cols = st.columns([3, 1.2, 1.2, 1.2])
            cols[0].markdown(f"**{title}**  \n`{item.filename}` • Profil: `{item.matched_profile or '-'}`")
            cols[1].caption(f"Länge: {format_duration(item.duration_seconds)}")
            cols[2].caption("🗑️ Drive gelöscht" if item.drive_trashed else "📁 Noch in Drive")
            if item.youtube_url:
                cols[3].link_button("▶️ YouTube", sanitize_display_url(item.youtube_url))

    st.divider()
    st.subheader("Letzte Bot-Läufe")
    runs = repository.list_upload_runs(limit=30)
    if not runs:
        st.caption("Noch keine Läufe protokolliert.")
        return

    rows = [
        {
            "Zeitpunkt": r.started_at,
            "Status": format_run_status_badge(r.status),
            "Quelle": r.trigger_source.value,
            "Profil": r.profile_name,
            "Dry-Run": "Ja" if r.dry_run else "Nein",
            "Gescannt": r.scanned_count,
            "Passend": r.eligible_count,
            "Hochgeladen": r.uploaded_count,
            "Fehler": r.failed_count,
            "Zusammenfassung": r.summary_message,
        }
        for r in runs
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)
