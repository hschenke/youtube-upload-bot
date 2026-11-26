"""Passwort-Schutz und Session-Token-Verwaltung für die Streamlit Web-App."""

from __future__ import annotations

import streamlit as st

from src.config.settings import AppSettings
from src.domain.enums import AuthRole
from src.security.auth import (
    LoginRateLimiter,
    generate_admin_token,
    resolve_credential_role,
)

_SESSION_TOKEN_KEY = "ytbot_auth_token"  # noqa: S105


@st.cache_resource
def _get_rate_limiter() -> LoginRateLimiter:
    return LoginRateLimiter()


def enforce_authentication(settings: AppSettings) -> AuthRole:
    """Prüft Login-Status über `APP_PASSWORD`, Query-Token oder Session-State."""
    expected_pw = settings.app_password.strip()
    if not expected_pw:
        return AuthRole.ADMIN

    query_token = str(st.query_params.get("token", "")).strip()
    session_token = str(st.session_state.get(_SESSION_TOKEN_KEY, "")).strip()

    for candidate in (session_token, query_token):
        role = resolve_credential_role(candidate, expected_pw)
        if role != AuthRole.GUEST:
            st.session_state[_SESSION_TOKEN_KEY] = candidate
            return role

    limiter = _get_rate_limiter()
    st.title("🔐 YouTube-Upload-Bot Login")
    locked, remaining_sec = limiter.is_locked_out()
    if locked:
        st.error(f"Zu viele Fehlversuche. Bitte in {remaining_sec} Sekunden erneut versuchen.")
        st.stop()

    with st.form("login_form"):
        entered = st.text_input("App-Passwort", type="password")
        submitted = st.form_submit_button("Anmelden", type="primary")

    if submitted:
        role = resolve_credential_role(entered, expected_pw)
        if role == AuthRole.ADMIN:
            limiter.reset()
            st.session_state[_SESSION_TOKEN_KEY] = generate_admin_token(expected_pw)
            st.rerun()
        limiter.record_failure()
        st.error("Ungültiges Passwort.")
    st.stop()
    return AuthRole.GUEST
