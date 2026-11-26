"""Einmaliges lokales Hilfsskript zum Erzeugen des Google OAuth Refresh Tokens."""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow
from src.config.constants import GOOGLE_LEAST_PRIVILEGE_SCOPES, GOOGLE_REQUIRED_SCOPES


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Startet den lokalen Google OAuth2 Consent Flow und gibt den Refresh Token aus.",
    )
    parser.add_argument("--client-id", default="", help="Google OAuth Client ID (oder GOOGLE_CLIENT_ID)")
    parser.add_argument("--client-secret", default="", help="Google OAuth Client Secret (oder GOOGLE_CLIENT_SECRET)")
    parser.add_argument(
        "--least-privilege-drive",
        action="store_true",
        help="Verwendet `drive.file` statt `drive` (sieht nur vom Bot angelegte Drive-Dateien).",
    )
    args = parser.parse_args(argv)

    load_dotenv()
    client_id = (args.client_id or os.getenv("GOOGLE_CLIENT_ID") or "").strip()
    client_secret = (args.client_secret or os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()

    if not client_id or not client_secret:
        print(
            "Fehler: GOOGLE_CLIENT_ID und GOOGLE_CLIENT_SECRET müssen gesetzt oder per CLI übergeben werden.",
            file=sys.stderr,
        )
        return 1

    scopes = list(GOOGLE_LEAST_PRIVILEGE_SCOPES if args.least_privilege_drive else GOOGLE_REQUIRED_SCOPES)
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, scopes=scopes)
    credentials = flow.run_local_server(
        port=0,
        access_type="offline",
        prompt="consent",
    )

    if not credentials.refresh_token:
        print(
            "Warnung: Google hat keinen Refresh Token zurückgegeben. "
            "Bitte App-Zugriff im Google-Konto widerrufen und erneut versuchen.",
            file=sys.stderr,
        )
        return 1

    print("\nOAuth erfolgreich! Bitte diesen Wert sicher in .env / GitHub Secrets / Streamlit Secrets eintragen:")
    print(f"GOOGLE_REFRESH_TOKEN={credentials.refresh_token}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
