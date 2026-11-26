# Projekt-Leitlinien: `youtube-upload-bot`

## Architektur & Regeln
- **Schichten:** `src/config` (Settings & Konstanten), `src/domain` (Enums, Exceptions, Dataclasses, Pydantic-Schemas), `src/security` (Auth, Sanitization, SSRF-Guard, Google OAuth), `src/storage` (SQLite & Turso Hrana v2), `src/media` (`ffprobe` Rotation-aware & Filter-Engine), `src/integrations` (Photos Picker, Drive Staging, YouTube v3), `src/ai` (Gemini Interactions + Files API), `src/notifications` (Resend/SMTP), `src/worker` (Pipeline & CLI), `src/ui` (Streamlit Views).
- **Gemini-Modelle:** Ausschließlich aktuelle Modelle (`gemini-3.8-flash`, `gemini-3.5-flash-lite`, `gemini-4-argon`) über `client.interactions.create(...)` verwenden. Niemals veraltete `gemini-2.5-*`/`2.0-*`/`1.5-*` Modelle nutzen.
- **Sicherheit:** Keine Secrets im Code oder Git; `validate_google_media_url` vor jedem Download mit Bearer-Token; `shell=False` bei `ffprobe`; `get_safe_filepath` gegen Path Traversal.
- **Qualität:** Vor jedem Commit `ruff check .` und `pytest -v` ausführen.
