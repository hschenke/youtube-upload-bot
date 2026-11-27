"""Zentrale Google OAuth2 Verwaltung: Web-PKCE-Flow, Multi-Account-DB und Refresh-Provider."""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from typing import TYPE_CHECKING
from urllib.parse import urlencode, urlparse

import requests
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from src.config.constants import (
    DEFAULT_HTTP_TIMEOUT_SECONDS,
    GOOGLE_OAUTH_AUTH_URI,
    GOOGLE_OAUTH_REVOKE_URI,
    GOOGLE_OAUTH_TOKEN_URI,
    GOOGLE_OAUTH_USERINFO_URI,
    GOOGLE_WEB_OAUTH_SCOPES,
    OAUTH_STATE_TTL_SECONDS,
    YOUTUBE_CHANNELS_API_URI,
)
from src.config.settings import AppSettings
from src.domain.exceptions import GoogleAuthError
from src.domain.models import GoogleAccountRecord
from src.security.crypto import decrypt_secret, encrypt_secret

if TYPE_CHECKING:
    from src.storage.repository import SqlBotRepository

logger = logging.getLogger(__name__)


def validate_oauth_redirect_uri(raw_uri: str) -> str:
    """Erlaubt nur gültige `https://` oder lokale `http://localhost` Redirect-URIs."""
    cleaned = (raw_uri or "").strip().rstrip("/")
    parsed = urlparse(cleaned)
    if parsed.scheme == "https" and parsed.netloc:
        return cleaned
    if parsed.scheme == "http" and (parsed.hostname or "").lower() in {"localhost", "127.0.0.1"}:
        return cleaned
    raise GoogleAuthError(
        "Ungültige Redirect-URI für Google OAuth (muss https:// oder http://localhost sein)."
    )


def _compute_pkce_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


class GoogleWebOAuthFlow:
    """Führt den browserbasierten Authorization-Code-PKCE-Flow für beliebige Google-Konten aus."""

    def __init__(
        self,
        settings: AppSettings,
        session: requests.Session | None = None,
    ) -> None:
        self._settings = settings
        self._http = session or requests.Session()

    def build_authorization_url(
        self,
        *,
        redirect_uri: str,
        repository: SqlBotRepository,
        initiated_by_admin: bool = True,
    ) -> tuple[str, str]:
        """Erstellt eine Google-Login-URL inkl. gespeichertem PKCE-Verifier & CSRF-State."""
        if not self._settings.has_google_client_configured:
            raise GoogleAuthError(
                "GOOGLE_CLIENT_ID oder GOOGLE_CLIENT_SECRET ist nicht konfiguriert."
            )
        if not self._settings.has_oauth_encryption_configured:
            raise GoogleAuthError(
                "OAUTH_ENCRYPTION_KEY fehlt. Bitte zuerst in Secrets/Environment hinterlegen."
            )

        clean_redirect = validate_oauth_redirect_uri(redirect_uri)
        state = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        code_challenge = _compute_pkce_challenge(code_verifier)

        repository.create_oauth_state(
            state=state,
            code_verifier=code_verifier,
            redirect_uri=clean_redirect,
            ttl_seconds=OAUTH_STATE_TTL_SECONDS,
            initiated_by_admin=initiated_by_admin,
        )

        query = urlencode(
            {
                "client_id": self._settings.google_client_id,
                "redirect_uri": clean_redirect,
                "response_type": "code",
                "scope": " ".join(GOOGLE_WEB_OAUTH_SCOPES),
                "access_type": "offline",
                "prompt": "consent select_account",
                "include_granted_scopes": "true",
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{GOOGLE_OAUTH_AUTH_URI}?{query}", state

    def handle_callback(
        self,
        *,
        code: str,
        state: str,
        repository: SqlBotRepository,
    ) -> tuple[GoogleAccountRecord, bool]:
        """Verifiziert State, tauscht Code gegen Tokens und speichert das Konto verschlüsselt."""
        clean_code = (code or "").strip()
        if not clean_code:
            raise GoogleAuthError("Kein Autorisierungscode von Google erhalten.")

        state_record = repository.consume_oauth_state(state)
        if state_record is None:
            raise GoogleAuthError("Ungültiger oder abgelaufener OAuth-State. Bitte Login neu starten.")

        token_payload = self._exchange_code(
            code=clean_code,
            code_verifier=state_record.code_verifier,
            redirect_uri=state_record.redirect_uri,
        )
        access_token = str(token_payload.get("access_token") or "").strip()
        if not access_token:
            raise GoogleAuthError("Google Token-Antwort enthielt kein Access Token.")

        userinfo = self._fetch_userinfo(access_token)
        account_id = str(userinfo.get("id") or "").strip()
        email = str(userinfo.get("email") or "").strip()
        display_name = str(userinfo.get("name") or email).strip()
        if not account_id or not email:
            raise GoogleAuthError("Google-Kontoinformationen (ID/E-Mail) konnten nicht geladen werden.")

        raw_refresh = str(token_payload.get("refresh_token") or "").strip()
        if raw_refresh:
            encrypted_refresh = encrypt_secret(raw_refresh, self._settings.oauth_encryption_key)
        else:
            existing = repository.get_google_account(account_id)
            if existing is None or not existing.encrypted_refresh_token:
                raise GoogleAuthError(
                    "Google hat keinen Refresh Token geliefert. Bitte App-Zugriff im Google-Konto "
                    "entfernen und erneut anmelden."
                )
            encrypted_refresh = existing.encrypted_refresh_token

        channel_id, channel_title = self._fetch_youtube_channel_best_effort(access_token)
        scopes_str = str(token_payload.get("scope") or "").strip()
        scopes = tuple(s for s in scopes_str.split() if s) or GOOGLE_WEB_OAUTH_SCOPES

        record = GoogleAccountRecord(
            account_id=account_id,
            email=email,
            display_name=display_name,
            youtube_channel_id=channel_id,
            youtube_channel_title=channel_title,
            encrypted_refresh_token=encrypted_refresh,
            scopes=scopes,
            is_active=True,
        )
        repository.upsert_google_account(record, set_active=True)
        saved = repository.get_google_account(account_id) or record
        return saved, state_record.initiated_by_admin

    def disconnect_account(
        self,
        account: GoogleAccountRecord,
        repository: SqlBotRepository,
    ) -> None:
        """Widerruft das Refresh Token bei Google (Best-Effort) und löscht das Konto aus der DB."""
        if account.encrypted_refresh_token and self._settings.has_oauth_encryption_configured:
            try:
                plain_token = decrypt_secret(
                    account.encrypted_refresh_token, self._settings.oauth_encryption_key
                )
                self._http.post(
                    GOOGLE_OAUTH_REVOKE_URI,
                    data={"token": plain_token},
                    timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
                )
            except Exception as exc:
                logger.warning("Token-Revoke bei Google übersprungen (%s).", type(exc).__name__)
        repository.delete_google_account(account.account_id)

    def _exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> dict[str, object]:
        try:
            resp = self._http.post(
                GOOGLE_OAUTH_TOKEN_URI,
                data={
                    "client_id": self._settings.google_client_id,
                    "client_secret": self._settings.google_client_secret,
                    "code": code,
                    "code_verifier": code_verifier,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
                timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise GoogleAuthError(f"Google Token-Austausch fehlgeschlagen: {exc}") from exc

        if resp.status_code != 200:
            raise GoogleAuthError(f"Google Token-Austausch abgelehnt (HTTP {resp.status_code}).")
        return dict(resp.json())

    def _fetch_userinfo(self, access_token: str) -> dict[str, object]:
        try:
            resp = self._http.get(
                GOOGLE_OAUTH_USERINFO_URI,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise GoogleAuthError(f"Google Userinfo-Abruf fehlgeschlagen: {exc}") from exc

        if resp.status_code != 200:
            raise GoogleAuthError(f"Google Userinfo HTTP {resp.status_code}.")
        return dict(resp.json())

    def _fetch_youtube_channel_best_effort(self, access_token: str) -> tuple[str | None, str | None]:
        try:
            resp = self._http.get(
                YOUTUBE_CHANNELS_API_URI,
                params={"part": "snippet", "mine": "true"},
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
            )
            if resp.status_code != 200:
                return None, None
            items = resp.json().get("items") or []
            if not items:
                return None, None
            ch = items[0]
            snippet = ch.get("snippet") or {}
            return str(ch.get("id") or "") or None, str(snippet.get("title") or "") or None
        except Exception:
            return None, None


class GoogleOAuthCredentialProvider:
    """Erstellt und aktualisiert `Credentials` aus aktivem DB-Konto oder Env-Fallback."""

    def __init__(
        self,
        settings: AppSettings,
        repository: SqlBotRepository | None = None,
        account_id: str | None = None,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._account_id = account_id

    def _resolve_account(self) -> GoogleAccountRecord | None:
        if self._repository is None:
            return None
        if self._account_id:
            return self._repository.get_google_account(self._account_id)
        return self._repository.get_active_google_account()

    def active_account_email(self) -> str | None:
        account = self._resolve_account()
        return account.email if account else None

    def has_connected_account(self) -> bool:
        if not self._settings.has_google_client_configured:
            return False
        account = self._resolve_account()
        if account is not None and account.encrypted_refresh_token:
            return self._settings.has_oauth_encryption_configured
        return bool(self._settings.google_refresh_token)

    def _resolve_refresh_token(self) -> str:
        account = self._resolve_account()
        if account is not None and account.encrypted_refresh_token:
            return decrypt_secret(
                account.encrypted_refresh_token,
                self._settings.oauth_encryption_key,
            )
        if self._settings.google_refresh_token:
            return self._settings.google_refresh_token
        raise GoogleAuthError(
            "Kein Google-Konto verbunden. Bitte in der Web-App unter 'System & Setup' "
            "über den Google-Login anmelden."
        )

    def get_credentials(self, force_refresh: bool = False) -> Credentials:
        """Liefert gültige, bei Bedarf frisch aktualisierte Google-OAuth-Credentials."""
        if not self._settings.has_google_client_configured:
            raise GoogleAuthError(
                "Google OAuth Client ist unvollständig konfiguriert "
                "(GOOGLE_CLIENT_ID oder GOOGLE_CLIENT_SECRET fehlt)."
            )

        refresh_token = self._resolve_refresh_token()
        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=GOOGLE_OAUTH_TOKEN_URI,
            client_id=self._settings.google_client_id,
            client_secret=self._settings.google_client_secret,
        )
        if force_refresh or not credentials.valid or not credentials.token:
            try:
                credentials.refresh(Request())
            except RefreshError as exc:
                logger.error("Google OAuth Token-Refresh fehlgeschlagen.")
                raise GoogleAuthError(
                    "Google OAuth Refresh Token ungültig oder widerrufen. "
                    "Bitte das Google-Konto im Dashboard unter 'System & Setup' neu verbinden."
                ) from exc
            except Exception as exc:
                logger.error("Unerwarteter Fehler beim Google OAuth Refresh: %s", type(exc).__name__)
                raise GoogleAuthError("Netzwerk- oder Konfigurationsfehler bei Google OAuth.") from exc
        return credentials

    def get_access_token(self) -> str:
        """Liefert einen aktuellen Bearer Access Token für REST-Clients (z. B. Photos Picker)."""
        creds = self.get_credentials()
        if not creds.token:
            raise GoogleAuthError("Kein gültiges Google Access Token erhalten.")
        return str(creds.token)
