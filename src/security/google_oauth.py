"""Zentrale Verwaltung der Google OAuth2 Credentials ohne Secret-Leaks."""

from __future__ import annotations

import logging

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from src.config.constants import GOOGLE_OAUTH_TOKEN_URI
from src.config.settings import AppSettings
from src.domain.exceptions import GoogleAuthError

logger = logging.getLogger(__name__)


class GoogleOAuthCredentialProvider:
    """Erstellt und aktualisiert `Credentials` aus `GOOGLE_CLIENT_ID`, `_SECRET` und `_REFRESH_TOKEN`."""

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings

    def get_credentials(self, force_refresh: bool = False) -> Credentials:
        """Liefert gültige, bei Bedarf frisch aktualisierte Google-OAuth-Credentials."""
        if not self._settings.has_google_oauth_configured:
            raise GoogleAuthError(
                "Google OAuth ist unvollständig konfiguriert "
                "(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET oder GOOGLE_REFRESH_TOKEN fehlt)."
            )

        credentials = Credentials(
            token=None,
            refresh_token=self._settings.google_refresh_token,
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
                    "Bitte `scripts/setup_google_oauth.py` erneut ausführen."
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
