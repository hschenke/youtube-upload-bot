# Projekt-Leitlinien: `youtube-upload-bot`

## Architektur & Regeln
- **Schichten:** `src/config` (Settings & Konstanten), `src/domain` (Enums, Exceptions, Dataclasses, Pydantic-Schemas), `src/security` (Auth, AES-256-GCM Crypto, Sanitization, SSRF-Guard, Google Web-OAuth PKCE), `src/storage` (SQLite & Turso Hrana v2, DB-Konten & DB-Settings), `src/media` (`ffprobe` Rotation-aware & Filter-Engine), `src/integrations` (Photos Picker, Drive Staging, YouTube v3), `src/ai` (Gemini Interactions + Files API), `src/notifications` (Resend/SMTP), `src/worker` (Pipeline & CLI), `src/ui` (Streamlit Views).
- **Secrets-Hygiene:** Ausschließlich echte Secrets (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `OAUTH_ENCRYPTION_KEY`, `GEMINI_API_KEY`, `TURSO_URL`, `TURSO_KEY`, `RESEND_API_KEY`, `APP_PASSWORD`, optional `GITHUB_TOKEN`/`SMTP_PASS`) in Env/Secrets speichern. Alle nicht-geheimen Konfigurationen liegen in der Datenbank (`app_settings`).
- **Gemini-Modelle:** Ausschließlich aktuelle Modelle (`gemini-3.8-flash`, `gemini-3.5-flash-lite`, `gemini-4-argon`) über `client.interactions.create(...)` verwenden. Niemals veraltete `gemini-2.5-*`/`2.0-*`/`1.5-*` Modelle nutzen.
- **Sicherheit:** Keine Secrets im Code oder Git; `validate_google_media_url` vor jedem Download mit Bearer-Token; `shell=False` bei `ffprobe`; `get_safe_filepath` gegen Path Traversal; OAuth Refresh Tokens ausschließlich AES-256-GCM-verschlüsselt in der DB.
- **Qualität:** Vor jedem Commit `ruff check .` und `pytest -v` ausführen.
