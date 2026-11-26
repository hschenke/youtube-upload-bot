# 🎬 YouTube-Upload-Bot

Autonomer YouTube-Upload-Bot, der Videos aus **Google Fotos** (über die offizielle **Google Photos Picker API**) in einen **Google Drive Staging-Ordner** übernimmt, nach konfigurierbaren Schemaregeln (z. B. **YouTube Shorts**: Portrait 9:16, 3–180 s, ältestes Aufnahmedatum zuerst) filtert, per **Gemini Video-Analyse** Titel, Beschreibung und Hashtags generiert und die Videos nach Zeitplan über **GitHub Actions** direkt zu **YouTube** hochlädt.

Nach erfolgreichem Upload wird die temporäre Kopie im Drive-Staging-Ordner automatisch in den Papierkorb verschoben (das Original bleibt sicher in Google Fotos).

---

## 🏗️ Architektur (Google Photos API 2025/2026-konform)

```text
Google Fotos (Picker UI im Streamlit-Dashboard)
   │  Streaming-Download (=dv) mit Host-Whitelist
   ▼
Google Drive Staging-Ordner (inkl. appProperties: photos_media_id, original_created_at)
   │  Turso Cloud DB / SQLite (Queue, Profile, Upload-Historie, 3x Duplikatschutz)
   ▼
GitHub Actions Cron (~18:00 DE-Zeit) / CLI-Worker
   ├─► ffprobe (Rotation-aware Portrait/Landscape & Längenprüfung)
   ├─► Gemini Interactions API + Files API (Titel, Beschreibung, #Shorts & Tags)
   ├─► YouTube Data API v3 (Resumable Upload, Made-for-Kids = False)
   ├─► Drive Staging Kopie → Papierkorb
   └─► E-Mail-Benachrichtigung (Resend / SMTP)
```

---

## 🚀 Einmaliges Setup

### 1. Google Cloud Console
1. Projekt anlegen oder bestehendes Projekt wählen.
2. Folgende APIs aktivieren:
   - **Google Photos Picker API** (`photospicker.googleapis.com`)
   - **Google Drive API** (`drive.googleapis.com`)
   - **YouTube Data API v3** (`youtube.googleapis.com`)
3. **OAuth-Zustimmungsbildschirm** einrichten (als *Testnutzer* deinen eigenen Google-Account hinzufügen, solange die App im Testmodus bleibt).
4. **OAuth 2.0 Client-ID** vom Typ **Desktop-App** erstellen (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`).

### 2. Google Refresh Token lokal erzeugen
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# GOOGLE_CLIENT_ID und GOOGLE_CLIENT_SECRET in .env eintragen, danach:
.\.venv\Scripts\python.exe scripts/setup_google_oauth.py
```
Den ausgegebenen `GOOGLE_REFRESH_TOKEN` in `.env`, in den **GitHub Repository Secrets** und in den **Streamlit Cloud Secrets** hinterlegen.

### 3. Turso DB, Gemini & Benachrichtigungen
- **Turso Cloud DB** (`TURSO_URL`, `TURSO_KEY`): Damit Streamlit Cloud und GitHub Actions denselben Queue- und Historien-Stand teilen. Lokal ohne Turso wird automatisch `data/youtube_bot.db` (SQLite) genutzt.
- **Gemini API** (`GEMINI_API_KEY`): Standardmodell `gemini-3.8-flash`.
- **Resend / SMTP** (`RESEND_API_KEY`, `EMAIL_TO`): Optionale E-Mails bei jedem Upload, Fehlern oder leerer Queue.

### 4. GitHub Secrets & Streamlit Cloud
In GitHub (`Settings → Secrets and variables → Actions`) folgende Secrets anlegen:
`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`, `GEMINI_API_KEY`, `TURSO_URL`, `TURSO_KEY`, sowie optional `RESEND_API_KEY`, `EMAIL_TO`, `APP_PASSWORD`, `STREAMLIT_APP_URL`, `GOOGLE_DRIVE_STAGING_FOLDER_ID`.

---

## 🧪 Lokal starten & testen

```powershell
# Tests & Security-Linting
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\pytest.exe -v

# Streamlit Dashboard starten
.\.venv\Scripts\streamlit.exe run streamlit_app.py

# Dry-Run des Workers lokal testen
.\.venv\Scripts\python.exe -m src.worker.cli_worker --profile shorts --dry-run
```
