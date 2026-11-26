"""View 3: Upload-Profile, Schema-Regeln und KI-Prompts bearbeiten."""

from __future__ import annotations

import streamlit as st

from src.config.settings import AppSettings
from src.domain.enums import PrivacyStatus, SelectionOrder, VideoOrientation
from src.domain.models import UploadProfile
from src.domain.schemas import normalize_hashtag
from src.storage.repository import SqlBotRepository


def _render_profile_editor(profile: UploadProfile, repository: SqlBotRepository) -> None:
    with st.form(f"profile_form_{profile.name}"):
        col1, col2, col3 = st.columns(3)
        display_name = col1.text_input("Anzeigename", value=profile.display_name)
        enabled = col2.checkbox("Profil aktiv", value=profile.enabled)
        orientation = col3.selectbox(
            "Orientierung",
            options=[o.value for o in VideoOrientation],
            index=[o.value for o in VideoOrientation].index(profile.orientation.value),
        )

        col4, col5, col6, col7 = st.columns(4)
        min_dur = col4.number_input(
            "Min. Länge (s)", min_value=0.0, max_value=43200.0, value=float(profile.min_duration_seconds or 0.0)
        )
        max_dur = col5.number_input(
            "Max. Länge (s)", min_value=1.0, max_value=43200.0, value=float(profile.max_duration_seconds or 180.0)
        )
        min_ratio = col6.number_input(
            "Min. Seitenverhältnis", min_value=0.1, max_value=5.0, value=float(profile.min_aspect_ratio or 0.45)
        )
        max_ratio = col7.number_input(
            "Max. Seitenverhältnis", min_value=0.1, max_value=5.0, value=float(profile.max_aspect_ratio or 0.85)
        )

        col8, col9, col10, col11 = st.columns(4)
        order = col8.selectbox(
            "Auswahlreihenfolge",
            options=[o.value for o in SelectionOrder],
            index=[o.value for o in SelectionOrder].index(profile.selection_order.value),
        )
        max_uploads = col9.number_input(
            "Uploads pro Lauf", min_value=1, max_value=20, value=int(profile.max_uploads_per_run)
        )
        privacy = col10.selectbox(
            "YouTube-Sichtbarkeit",
            options=[p.value for p in PrivacyStatus],
            index=[p.value for p in PrivacyStatus].index(profile.privacy_status.value),
        )
        language = col11.text_input("KI-Sprache (ISO)", value=profile.language)

        col12, col13 = st.columns(2)
        date_from = col12.text_input("Aufnahmedatum ab (YYYY-MM-DD, optional)", value=profile.date_from or "")
        date_to = col13.text_input("Aufnahmedatum bis (YYYY-MM-DD, optional)", value=profile.date_to or "")

        req_hashtags = st.text_input(
            "Pflicht-Hashtags (kommagetrennt)",
            value=", ".join(profile.required_hashtags),
        )
        footer = st.text_input("Fester Beschreibungs-Footer", value=profile.description_footer)
        ai_prompt = st.text_area("Gemini Analyse-Prompt", value=profile.ai_prompt, height=110)

        if st.form_submit_button("💾 Profil speichern", type="primary"):
            parsed_hashtags = tuple(
                norm for raw in req_hashtags.split(",") if (norm := normalize_hashtag(raw))
            )
            updated = UploadProfile(
                name=profile.name,
                display_name=display_name.strip() or profile.name,
                enabled=enabled,
                orientation=VideoOrientation(orientation),
                min_aspect_ratio=float(min_ratio),
                max_aspect_ratio=float(max_ratio),
                min_duration_seconds=float(min_dur),
                max_duration_seconds=float(max_dur),
                min_width=profile.min_width,
                min_height=profile.min_height,
                date_from=date_from.strip() or None,
                date_to=date_to.strip() or None,
                include_filename_patterns=profile.include_filename_patterns,
                exclude_filename_patterns=profile.exclude_filename_patterns,
                selection_order=SelectionOrder(order),
                max_uploads_per_run=int(max_uploads),
                privacy_status=PrivacyStatus(privacy),
                category_id=profile.category_id,
                made_for_kids=profile.made_for_kids,
                language=language.strip() or "en",
                required_hashtags=parsed_hashtags,
                default_tags=profile.default_tags,
                description_footer=footer.strip(),
                ai_prompt=ai_prompt.strip(),
            )
            repository.upsert_profile(updated)
            st.success(f"Profil '{profile.name}' gespeichert.")
            st.rerun()


def render_profiles_view(settings: AppSettings, repository: SqlBotRepository) -> None:  # noqa: ARG001
    st.header("🎛️ Upload-Profile & KI-Prompts")
    profiles = repository.list_profiles()
    if profiles:
        tabs = st.tabs([f"{'🟢' if p.enabled else '⚪'} {p.name}" for p in profiles])
        for tab, profile in zip(tabs, profiles, strict=True):
            with tab:
                _render_profile_editor(profile, repository)

    st.divider()
    with st.expander("➕ Neues Profil anlegen"), st.form("new_profile_form"):
        new_name = st.text_input("Technischer Profilname (z. B. travel_reels)")
        new_display = st.text_input("Anzeigename")
        new_orient = st.selectbox("Orientierung", options=[o.value for o in VideoOrientation])
        if st.form_submit_button("Profil anlegen"):
            clean = new_name.strip().lower().replace(" ", "_")
            if not clean:
                st.error("Bitte einen Profilnamen angeben.")
            else:
                repository.upsert_profile(
                    UploadProfile(
                        name=clean,
                        display_name=new_display.strip() or clean,
                        enabled=False,
                        orientation=VideoOrientation(new_orient),
                    )
                )
                st.success(f"Profil '{clean}' angelegt.")
                st.rerun()
