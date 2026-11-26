"""Tests für Auth, Input-Sanitization, SSRF-Guard und Konfiguration."""

from __future__ import annotations

from pathlib import Path

import pytest
from src.config.settings import load_app_settings
from src.domain.enums import AuthRole
from src.domain.exceptions import InputValidationError
from src.security.auth import (
    LoginRateLimiter,
    generate_admin_token,
    generate_readonly_token,
    resolve_credential_role,
    verify_admin_token,
    verify_readonly_token,
)
from src.security.sanitization import (
    get_safe_filepath,
    mask_email_for_log,
    sanitize_display_url,
    sanitize_filename,
    sanitize_youtube_description,
    sanitize_youtube_title,
    validate_email_address,
    validate_google_media_url,
)


def test_admin_and_readonly_tokens_and_rate_limiter() -> None:
    pw = "SuperStrongPass!123"
    adm = generate_admin_token(pw, issued_at=1_700_000_000)
    assert adm.startswith("adm:")
    assert verify_admin_token(adm, pw, max_age_seconds=10_000_000_000)
    assert not verify_admin_token(adm, "wrong-password", max_age_seconds=10_000_000_000)

    ro = generate_readonly_token(pw, scope="history")
    assert verify_readonly_token(ro, pw)
    assert resolve_credential_role(ro, pw) == AuthRole.READONLY
    assert resolve_credential_role("wrong", pw) == AuthRole.GUEST
    assert resolve_credential_role("", "") == AuthRole.ADMIN

    limiter = LoginRateLimiter(max_attempts=2, lockout_seconds=60)
    assert limiter.is_locked_out() == (False, 0)
    limiter.record_failure()
    limiter.record_failure()
    locked, rem = limiter.is_locked_out()
    assert locked and rem > 0
    limiter.reset()
    assert limiter.is_locked_out() == (False, 0)


def test_path_traversal_and_filename_sanitization(tmp_path: Path) -> None:
    assert sanitize_filename("../../etc/passwd") == "passwd"
    safe = get_safe_filepath(tmp_path, "folder/../clip 01.mp4")
    assert safe.parent == tmp_path.resolve()
    assert safe.name == "clip_01.mp4"


def test_google_media_url_ssrf_whitelist() -> None:
    valid = "https://lh3.googleusercontent.com/lr/abc123"
    assert validate_google_media_url(valid) == valid

    for bad in (
        "http://lh3.googleusercontent.com/lr/abc123",
        "https://127.0.0.1/video.mp4",
        "https://169.254.169.254/latest/meta-data",
        "https://evil.example.com/steal-token",
    ):
        with pytest.raises(InputValidationError):
            validate_google_media_url(bad)


def test_youtube_and_email_sanitization() -> None:
    assert sanitize_youtube_title("Hello <script>World</script>   test") == "Hello scriptWorld/script test"
    assert len(sanitize_youtube_title("A" * 150)) == 100
    assert "<" not in sanitize_youtube_description("Desc <tag>")
    assert sanitize_display_url("javascript:alert(1)") == "#"
    assert sanitize_display_url("https://youtube.com/shorts/abc") == "https://youtube.com/shorts/abc"
    assert validate_email_address("holger@example.com") == "holger@example.com"
    assert mask_email_for_log("holger@example.com") == "ho***@example.com"
    with pytest.raises(InputValidationError):
        validate_email_address("bad\nheader@example.com")


def test_load_app_settings_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_MODEL", "deprecated-legacy-model")
    settings = load_app_settings(
        yaml_path=Path("config/settings.yaml"),
        dotenv_path=tmp_path / "missing.env",
    )
    assert settings.gemini_model == "gemini-3.8-flash"
    assert any(p.name == "shorts" and p.enabled for p in settings.default_profiles)
    assert any(p.name == "landscape" and not p.enabled for p in settings.default_profiles)
