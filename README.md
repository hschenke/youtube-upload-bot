# 🎬 YouTube-Upload-Bot

Autonomer YouTube-Upload-Bot, der Videos aus **Google Fotos** (über die offizielle **Google Photos Picker API**) in einen **Google Drive Staging-Ordner** übernimmt, nach konfigurierbaren Schemaregeln (z. B. **YouTube Shorts**: Portrait 9:16, 3–180 s, ältestes Aufnahmedatum zuerst) filtert, per **Gemini Video-Analyse** Titel, Beschreibung und Hashtags generiert und die Videos nach Zeitplan über **GitHub Actions** oder direkt aus der **Streamlit Web-App** zu **YouTube** hochlädt.

Nach erfolgreichem Upload wird die temporäre Kopie im Drive-Staging-Ordner automatisch in den Papierkorb verschoben (das Original bleibt sicher in Google Fotos).

---

## 🏗️ Architektur (100 % Remote + Multi-Account Web-OAuth)

```text
Streamlit Cloud Web-App (Public Repo, inkl. packages.txt -> ffmpeg)
   ├─► Google Web-OAuth Login (PKCE + AES-256-GCM verschlüsselter Token in Turso)
   ├─► Google Photos Picker UI → Streaming nach Google Drive Staging
   ├─► Direkte Test- & Upload-Ausführung in der Web-App (Dry-Run & Live)
   └─► Profile, KI-Prompts & Non-Secret Settings zentral in Turso DB

GitHub Actions Cron (~18:00 DE-Zeit, nutzt dieselben Turso-Daten & Secrets)
   ├─► ffprobe (Rotation-aware Portrait/Landscape & Längenprüfung)
   ├─► Gemini Interactions API + Files API (Titel, Beschreibung, #Shorts & Tags)
   ├─► YouTube Data API v3 (Resumable Upload, Made-for-Kids = False)
   ├─► Drive Staging Kopie → Papierkorb
   └─► E-Mail-Benachrichtigung (Resend / SMTP)
```

---

## 🚀 Einmaliges Setup

### 1. Cloud-Datenbank (Turso)
1. Auf https://app.turso.tech eine Datenbank anlegen (z. B. `youtube-upload-bot` in `aws-eu-west-1`).
2. `TURSO_URL` und `TURSO_KEY` als Secret bei GitHub und Streamlit Cloud eintragen.

### 2. Google Cloud Console (Web-OAuth für beliebige Google-Accounts)
1. Projekt in https://console.cloud.google.com öffnen oder anlegen.
2. **APIs aktivieren:**
   - **Google Photos Picker API**
   - **Google Drive API**
   - **YouTube Data API v3**
3. **OAuth-Zustimmungsbildschirm:** Typ *Extern*, gewünschte Google-Konten als *Testnutzer* hinzufügen (oder App verifizieren lassen).
4. **OAuth 2.0 Client-ID** vom Typ **Webanwendung** erstellen:
   - **Autorisierte Weiterleitungs-URIs (Redirect URIs):**
     - deine Streamlit-Cloud-URL (z. B. `https://deine-app.streamlit.app`)
     - optional für lokale Tests: `http://localhost:8501`
   - `GOOGLE_CLIENT_ID` und `GOOGLE_CLIENT_SECRET` als Secret hinterlegen.

### 3. Nur echte Secrets hinterlegen
Ausschließlich diese Secrets werden bei **GitHub Actions** und **Streamlit Cloud** benötigt:
`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `OAUTH_ENCRYPTION_KEY`, `GEMINI_API_KEY`, `TURSO_URL`, `TURSO_KEY`, `RESEND_API_KEY`, `APP_PASSWORD`.

Alle anderen Einstellungen (`GEMINI_MODEL`, `GOOGLE_DRIVE_STAGING_FOLDER_NAME`, `EMAIL_TO`, `EMAIL_FROM`, `EMAIL_PROVIDER`, `STREAMLIT_APP_URL`) stellst du bequem in der Web-App unter **⚙️ System & Setup** ein – sie landen zentral in der Datenbank.

### 4. Anmelden & direkt in der Web-App testen
1. Streamlit Cloud App (`streamlit_app.py`) auf dem öffentlichen Repo `hschenke/youtube-upload-bot` deployen.
2. In der Web-App unter **⚙️ System & Setup** die `STREAMLIT_APP_URL` speichern, auf **🔗 Neues Google-Konto verbinden** klicken und im Browser mit dem gewünschten Google-Account einloggen.
3. Unter **📸 Google Fotos Import** ein Hochkant-Video auswählen.
4. Unter **🎬 Video-Queue** direkt auf **🧪 Testlauf (Dry-Run) direkt hier starten** klicken und Ergebnis prüfen – anschließend live hochladen oder den täglichen GitHub-Cron laufen lassen.

---

## 🧪 Lokal starten & testen

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\pytest.exe -v
.\.venv\Scripts\streamlit.exe run streamlit_app.py
```
