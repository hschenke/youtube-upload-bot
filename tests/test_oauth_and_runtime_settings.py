"""Tests für AES-256-GCM Token-Verschlüsselung, Google Web-OAuth PKCE & DB Runtime-Settings."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from src.config.settings import load_app_settings
from src.domain.exceptions import GoogleAuthError
from src.security.crypto import decrypt_secret, encrypt_secret, generate_encryption_key
from src.security.google_oauth import GoogleOAuthCredentialProvider, GoogleWebOAuthFlow
from src.storage.repository import create_repository


def test_aes_gcm_encryption_roundtrip_and_tamper_detection() -> None:
    key = generate_encryption_key()
    blob = encrypt_secret("1//0gFakeRefreshToken", key)
    assert blob.startswith("v1:")
    assert "FakeRefreshToken" not in blob
    assert decrypt_secret(blob, key) == "1//0gFakeRefreshToken"

    with pytest.raises(GoogleAuthError):
        decrypt_secret(blob, generate_encryption_key())

    tampered = blob[:-4] + ("AAAA" if not blob.endswith("AAAA") else "BBBB")
    with pytest.raises(GoogleAuthError):
        decrypt_secret(tampered, key)

    # Passphrase-Fallback via HKDF funktioniert ebenfalls stabil
    pass_blob = encrypt_secret("1//token-via-passphrase", "my-passphrase-secret")
    assert decrypt_secret(pass_blob, "my-passphrase-secret") == "1//token-via-passphrase"


def test_google_web_oauth_flow_pkce_state_multi_account_and_disconnect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_DB_PATH", str(tmp_path / "oauth.db"))
    monkeypatch.delenv("TURSO_URL", raising=False)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-123.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret-xyz")
    monkeypatch.setenv("OAUTH_ENCRYPTION_KEY", generate_encryption_key())

    settings = load_app_settings(yaml_path=Path("config/settings.yaml"), dotenv_path=None)
    repo = create_repository(settings)

    class FakeSession(requests.Session):
        def __init__(self) -> None:
            super().__init__()
            self.revoked_tokens: list[str] = []
            self.user_idx = 0

        def post(self, url: str, **kwargs: object) -> object:
            if "revoke" in url:
                data = kwargs.get("data") or {}
                self.revoked_tokens.append(str(data.get("token") or ""))
                return SimpleNamespace(status_code=200)
            self.user_idx += 1
            return SimpleNamespace(
                status_code=200,
                json=lambda: {
                    "access_token": f"access_{self.user_idx}",
                    "refresh_token": f"1//refresh_{self.user_idx}",
                    "scope": "openid email https://www.googleapis.com/auth/youtube.upload",
                },
            )

        def get(self, url: str, **kwargs: object) -> object:
            if "userinfo" in url:
                idx = self.user_idx
                return SimpleNamespace(
                    status_code=200,
                    json=lambda: {
                        "id": f"uid_{idx}",
                        "email": f"user{idx}@example.com",
                        "name": f"User {idx}",
                    },
                )
            return SimpleNamespace(
                status_code=200,
                json=lambda: {
                    "items": [{"id": f"ch_{self.user_idx}", "snippet": {"title": f"Kanal {self.user_idx}"}}]
                },
            )

    fake_http = FakeSession()
    flow = GoogleWebOAuthFlow(settings, session=fake_http)

    try:
        auth_url_1, state_1 = flow.build_authorization_url(
            redirect_uri="https://my-bot.streamlit.app",
            repository=repo,
            initiated_by_admin=True,
        )
        assert "code_challenge=" in auth_url_1
        assert "code_challenge_method=S256" in auth_url_1

        acc1, was_admin = flow.handle_callback(code="code-1", state=state_1, repository=repo)
        assert was_admin is True
        assert acc1.email == "user1@example.com"
        assert acc1.youtube_channel_title == "Kanal 1"
        assert acc1.is_active is True

        # Replay desselben States muss fehlschlagen
        with pytest.raises(GoogleAuthError):
            flow.handle_callback(code="code-1", state=state_1, repository=repo)

        # Zweites Konto verbinden -> wird aktiv
        _, state_2 = flow.build_authorization_url(
            redirect_uri="http://localhost:8501",
            repository=repo,
        )
        acc2, _ = flow.handle_callback(code="code-2", state=state_2, repository=repo)
        assert acc2.email == "user2@example.com"
        assert len(repo.list_google_accounts()) == 2

        provider = GoogleOAuthCredentialProvider(settings, repository=repo)
        assert provider.has_connected_account() is True
        assert provider.active_account_email() == "user2@example.com"
        assert provider._resolve_refresh_token() == "1//refresh_2"

        # Umschalten auf erstes Konto
        assert repo.set_active_google_account(acc1.account_id)
        assert provider.active_account_email() == "user1@example.com"
        assert provider._resolve_refresh_token() == "1//refresh_1"

        # Trennen widerruft Token & löscht Konto
        flow.disconnect_account(acc1, repo)
        assert fake_http.revoked_tokens == ["1//refresh_1"]
        remaining = repo.list_google_accounts()
        assert [a.account_id for a in remaining] == [acc2.account_id]
    finally:
        repo.close()


def test_runtime_settings_stored_and_loaded_from_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_DB_PATH", str(tmp_path / "settings.db"))
    monkeypatch.delenv("TURSO_URL", raising=False)
    base = load_app_settings(yaml_path=Path("config/settings.yaml"), dotenv_path=None)
    repo = create_repository(base)

    try:
        repo.save_runtime_settings(
            {
                "gemini_model": "gemini-4-argon",
                "drive_staging_folder_name": "my-custom-staging",
                "email_provider": "smtp",
                "email_to": "alerts@example.com",
                "email_from": "Bot <bot@example.com>",
                "notify_on_upload": "false",
                "streamlit_app_url": "https://ytbot.streamlit.app",
            }
        )
        loaded = repo.load_runtime_settings(base)
        assert loaded.gemini_model == "gemini-4-argon"
        assert loaded.drive_staging_folder_name == "my-custom-staging"
        assert loaded.email_provider == "smtp"
        assert loaded.email_to == "alerts@example.com"
        assert loaded.email_from == "Bot <bot@example.com>"
        assert loaded.notify_on_upload is False
        assert loaded.streamlit_app_url == "https://ytbot.streamlit.app"
    finally:
        repo.close()
