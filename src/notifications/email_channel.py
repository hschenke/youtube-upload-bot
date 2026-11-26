"""E-Mail-Zustellung via Resend HTTPS API oder SMTP-Fallback ohne PII-Leaks."""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

from src.config.constants import EMAIL_HTTP_TIMEOUT_SECONDS
from src.config.settings import AppSettings
from src.domain.exceptions import InputValidationError
from src.domain.models import UploadResult, UploadRunRecord
from src.notifications.email_renderer import (
    build_dashboard_history_url,
    render_empty_queue_email,
    render_run_error_email,
    render_upload_success_email,
)
from src.security.sanitization import mask_email_for_log, validate_email_address

logger = logging.getLogger(__name__)
_RESEND_ENDPOINT = "https://api.resend.com/emails"


class EmailNotificationChannel:
    """Sendet Status-, Erfolgs- und Fehler-E-Mails via Resend oder SMTP."""

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings

    def is_configured(self) -> bool:
        return self._settings.has_email_configured

    def send_upload_success(
        self,
        result: UploadResult,
        *,
        profile_name: str,
        remaining_in_queue: int,
    ) -> bool:
        if not self._settings.notify_on_upload:
            return False
        dash_url = build_dashboard_history_url(
            self._settings.streamlit_app_url,
            self._settings.app_password,
        )
        html_body = render_upload_success_email(
            result,
            profile_name=profile_name,
            remaining_in_queue=remaining_in_queue,
            dashboard_url=dash_url,
        )
        return self._send(f"🎬 Uploaded: {result.title[:80]}", html_body)

    def send_empty_queue_notice(self, profile_name: str) -> bool:
        if not self._settings.notify_on_empty_queue:
            return False
        dash_url = build_dashboard_history_url(
            self._settings.streamlit_app_url,
            self._settings.app_password,
        )
        html_body = render_empty_queue_email(profile_name, dashboard_url=dash_url)
        return self._send("📭 YouTube-Upload-Bot: Queue ist leer", html_body)

    def send_error_notice(self, run: UploadRunRecord, error_summary: str) -> bool:
        if not self._settings.notify_on_error:
            return False
        html_body = render_run_error_email(run, error_summary)
        return self._send(f"⚠️ YouTube-Upload-Bot Fehler ({run.profile_name or 'all'})", html_body)

    def send_test_email(self, override_recipient: str = "") -> tuple[bool, str]:
        raw_to = override_recipient.strip() or self._settings.email_to.strip()
        if not raw_to:
            return False, "Keine Ziel-E-Mail-Adresse konfiguriert."
        try:
            recipient = validate_email_address(raw_to)
        except InputValidationError as exc:
            return False, str(exc)

        if not self.is_configured():
            return False, "E-Mail-Provider ist nicht vollständig konfiguriert."

        html_body = (
            "<div style='font-family:sans-serif;padding:20px;'>"
            "<h2>✅ YouTube-Upload-Bot E-Mail-Test erfolgreich</h2>"
            "<p>Dein Benachrichtigungskanal ist aktiv und einsatzbereit.</p></div>"
        )
        ok = self._deliver(recipient, "✅ YouTube-Upload-Bot: Test-Benachrichtigung", html_body)
        if ok:
            return True, f"Test-E-Mail erfolgreich an {mask_email_for_log(recipient)} gesendet."
        return False, "E-Mail-Versand fehlgeschlagen – Zugangsdaten prüfen."

    def _send(self, subject: str, html_body: str) -> bool:
        raw_to = self._settings.email_to.strip()
        if not raw_to or not self.is_configured():
            return False
        try:
            recipient = validate_email_address(raw_to)
        except InputValidationError as exc:
            logger.warning("Ungültige EMAIL_TO Konfiguration: %s", exc)
            return False
        return self._deliver(recipient, subject, html_body)

    def _deliver(self, recipient: str, subject: str, html_body: str) -> bool:
        if self._settings.email_provider == "smtp":
            return self._send_via_smtp(recipient, subject, html_body)
        return self._send_via_resend(recipient, subject, html_body)

    def _send_via_resend(self, recipient: str, subject: str, html_body: str) -> bool:
        masked = mask_email_for_log(recipient)
        try:
            resp = requests.post(
                _RESEND_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {self._settings.resend_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": self._settings.email_from,
                    "to": [recipient],
                    "subject": subject,
                    "html": html_body,
                },
                timeout=EMAIL_HTTP_TIMEOUT_SECONDS,
            )
            if resp.status_code in {200, 201}:
                logger.info("E-Mail via Resend erfolgreich an %s gesendet.", masked)
                return True
            logger.error("Resend API antwortete mit HTTP %d.", resp.status_code)
            return False
        except requests.RequestException as exc:
            logger.error("Netzwerkfehler beim Resend-Versand an %s: %s", masked, exc)
            return False

    def _send_via_smtp(self, recipient: str, subject: str, html_body: str) -> bool:
        masked = mask_email_for_log(recipient)
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._settings.email_from
        msg["To"] = recipient
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        try:
            with smtplib.SMTP(
                self._settings.smtp_host,
                self._settings.smtp_port,
                timeout=EMAIL_HTTP_TIMEOUT_SECONDS,
            ) as smtp:
                smtp.starttls()
                smtp.login(self._settings.smtp_user, self._settings.smtp_pass)
                smtp.sendmail(self._settings.email_from, [recipient], msg.as_string())
            logger.info("E-Mail via SMTP erfolgreich an %s gesendet.", masked)
            return True
        except Exception as exc:
            logger.error("SMTP-Versand an %s fehlgeschlagen: %s", masked, type(exc).__name__)
            return False
