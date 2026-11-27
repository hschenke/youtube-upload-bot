"""AES-256-GCM Verschlüsselung für gespeicherte Google OAuth Refresh Tokens."""

from __future__ import annotations

import base64
import binascii
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from src.domain.exceptions import GoogleAuthError

_BLOB_VERSION = "v1"
_NONCE_BYTES = 12
_ASSOCIATED_DATA = b"google_refresh_token_v1"
_HKDF_SALT = b"youtube-upload-bot-oauth-v1"
_HKDF_INFO = b"refresh-token"


def generate_encryption_key() -> str:
    """Erzeugt einen kryptografisch sicheren 32-Byte Base64url-Schlüssel für `OAUTH_ENCRYPTION_KEY`."""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")


def _derive_aes_key(key_material: str) -> bytes:
    clean = (key_material or "").strip()
    if not clean:
        raise GoogleAuthError(
            "OAUTH_ENCRYPTION_KEY fehlt. Ohne Schlüssel können OAuth-Tokens nicht sicher gespeichert werden."
        )

    padded = clean + "=" * (-len(clean) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        if len(decoded) == 32:
            return decoded
    except (binascii.Error, UnicodeEncodeError):
        pass

    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_HKDF_SALT,
        info=_HKDF_INFO,
    )
    return hkdf.derive(clean.encode("utf-8"))


def encrypt_secret(plaintext: str, key_material: str) -> str:
    """Verschlüsselt ein Secret mit AES-256-GCM in das Format `v1:<nonce>:<ciphertext>`."""
    clean_text = (plaintext or "").strip()
    if not clean_text:
        raise GoogleAuthError("Leeres Secret darf nicht verschlüsselt werden.")

    aes_key = _derive_aes_key(key_material)
    nonce = secrets.token_bytes(_NONCE_BYTES)
    ciphertext = AESGCM(aes_key).encrypt(nonce, clean_text.encode("utf-8"), _ASSOCIATED_DATA)
    nonce_b64 = base64.urlsafe_b64encode(nonce).decode("ascii")
    cipher_b64 = base64.urlsafe_b64encode(ciphertext).decode("ascii")
    return f"{_BLOB_VERSION}:{nonce_b64}:{cipher_b64}"


def decrypt_secret(token_blob: str, key_material: str) -> str:
    """Entschlüsselt ein mit `encrypt_secret` erzeugtes AES-256-GCM-Token."""
    parts = (token_blob or "").strip().split(":", 2)
    if len(parts) != 3 or parts[0] != _BLOB_VERSION:
        raise GoogleAuthError("Ungültiges Format des verschlüsselten OAuth-Tokens.")

    aes_key = _derive_aes_key(key_material)
    try:
        nonce = base64.urlsafe_b64decode(parts[1].encode("ascii"))
        ciphertext = base64.urlsafe_b64decode(parts[2].encode("ascii"))
        plaintext = AESGCM(aes_key).decrypt(nonce, ciphertext, _ASSOCIATED_DATA)
        return plaintext.decode("utf-8")
    except (binascii.Error, InvalidTag, UnicodeDecodeError, ValueError) as exc:
        raise GoogleAuthError(
            "OAuth-Token konnte nicht entschlüsselt werden (OAUTH_ENCRYPTION_KEY prüfen oder Konto neu verbinden)."
        ) from exc
