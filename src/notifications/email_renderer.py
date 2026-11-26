"""XSS-sichere HTML-Renderer für E-Mail-Benachrichtigungen."""

from __future__ import annotations

import html
from urllib.parse import urlencode

from src.domain.models import UploadResult, UploadRunRecord
from src.security.auth import generate_readonly_token
from src.security.sanitization import sanitize_display_url


def build_dashboard_history_url(base_url: str, app_password: str) -> str:
    """Erzeugt optional einen signierten Direktlink zur Upload-Historie."""
    safe_base = sanitize_display_url(base_url)
    if safe_base == "#":
        return ""
    params: dict[str, str] = {"view": "history"}
    ro_token = generate_readonly_token(app_password, scope="history")
    if ro_token:
        params["token"] = ro_token
    sep = "&" if "?" in safe_base else "?"
    return f"{safe_base}{sep}{urlencode(params)}"


def render_upload_success_email(
    result: UploadResult,
    *,
    profile_name: str,
    remaining_in_queue: int,
    dashboard_url: str = "",
) -> str:
    """Erzeugt eine saubere HTML-Mail nach erfolgreichem YouTube-Upload."""
    safe_title = html.escape(result.title)
    safe_profile = html.escape(profile_name)
    safe_yt_url = html.escape(sanitize_display_url(result.youtube_url), quote=True)
    safe_privacy = html.escape(result.privacy_status.value)

    dash_btn = ""
    if dashboard_url:
        safe_dash = html.escape(sanitize_display_url(dashboard_url), quote=True)
        dash_btn = (
            f"<a href='{safe_dash}' style='margin-left:10px;color:#58a6ff;"
            "text-decoration:none;font-size:14px;'>Dashboard öffnen →</a>"
        )

    return (
        "<div style='font-family:Segoe UI,Arial,sans-serif;max-width:600px;"
        "padding:20px;background:#0d1117;color:#f0f6fc;border-radius:10px;'>"
        "<h2 style='margin-top:0;color:#ff4b4b;'>🎬 Neues YouTube-Video hochgeladen</h2>"
        f"<p><b>Titel:</b> {safe_title}</p>"
        f"<p><b>Profil:</b> {safe_profile} &nbsp;|&nbsp; <b>Sichtbarkeit:</b> {safe_privacy}</p>"
        f"<p><b>Verbleibende Videos in Queue:</b> {int(remaining_in_queue)}</p>"
        "<p style='margin-top:20px;'>"
        f"<a href='{safe_yt_url}' style='background:#ff0033;color:#ffffff;"
        "padding:10px 16px;border-radius:6px;text-decoration:none;font-weight:bold;'>"
        "Auf YouTube ansehen</a>"
        f"{dash_btn}</p></div>"
    )


def render_empty_queue_email(profile_name: str, dashboard_url: str = "") -> str:
    """Informiert den Nutzer, wenn keine passenden Videos mehr in Drive gestagt sind."""
    safe_profile = html.escape(profile_name or "alle aktiven Profile")
    dash_hint = ""
    if dashboard_url:
        safe_dash = html.escape(sanitize_display_url(dashboard_url), quote=True)
        dash_hint = f"<p><a href='{safe_dash}' style='color:#58a6ff;'>Jetzt im Dashboard neue Videos importieren →</a></p>"
    return (
        "<div style='font-family:Segoe UI,Arial,sans-serif;max-width:600px;"
        "padding:20px;background:#0d1117;color:#f0f6fc;border-radius:10px;'>"
        "<h2 style='margin-top:0;color:#f2cc60;'>📭 Video-Queue ist leer</h2>"
        f"<p>Für <b>{safe_profile}</b> wurde kein passendes Video im Google Drive "
        "Staging-Ordner gefunden.</p>"
        "<p>Bitte wähle über den Google Photos Picker im Dashboard neue Videos aus.</p>"
        f"{dash_hint}</div>"
    )


def render_run_error_email(run: UploadRunRecord, error_summary: str) -> str:
    """Informiert über fehlgeschlagene Upload-Läufe ohne Secrets preiszugeben."""
    safe_run = html.escape(run.run_id)
    safe_profile = html.escape(run.profile_name or "all")
    safe_err = html.escape(error_summary[:600])
    return (
        "<div style='font-family:Segoe UI,Arial,sans-serif;max-width:600px;"
        "padding:20px;background:#0d1117;color:#f0f6fc;border-radius:10px;'>"
        "<h2 style='margin-top:0;color:#ff7b72;'>⚠️ YouTube-Upload-Bot Fehler</h2>"
        f"<p><b>Run-ID:</b> {safe_run} &nbsp;|&nbsp; <b>Profil:</b> {safe_profile}</p>"
        f"<p><b>Fehlermeldung:</b></p><pre style='background:#161b22;padding:12px;"
        f"border-radius:6px;white-space:pre-wrap;'>{safe_err}</pre></div>"
    )
