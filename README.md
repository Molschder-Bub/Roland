# Roland

Ein lokaler Download- und Konvertierungs-Helfer für Medien aus dem Web – läuft komplett auf deinem eigenen Computer, kein Upload, keine Cloud, kein Tracking.

---

## Funktionen

### Download
- Unterstützte Plattformen: **YouTube, X / Twitter, Instagram, TikTok, Facebook, Vimeo, SoundCloud, Reddit, Twitch**
- Ausgabeformate: **MP3, MP4, M4A, WebM**
- Qualitätsauswahl für Videos: **Beste, 4K, 1440p, 1080p, 720p, 480p, 360p**
- Live-Fortschrittsanzeige während des Downloads

### Transkription
- Lokale Spracherkennung mit [faster-whisper](https://github.com/SYSTRAN/faster-whisper) – läuft komplett offline auf deinem Computer
- Automatische Zeitmarken in ~30-Sekunden-Abschnitten
- Such- und Sprungfunktion innerhalb des Transkripts
- Transkript als Textdatei speichern

### Feedback
- Eingebautes Feedback-Formular, das Nachrichten direkt per Telegram-Bot zustellt (optional, eigene Konfiguration nötig)

---

## Installation & Start

Roland läuft auf **macOS, Windows und Linux** – die gesamte App ist eine einzige Python-Datei (`server.py`) mit eingebettetem Webinterface.

1. Repository herunterladen / klonen
2. Starten:
   - **macOS:** `Roland.app` doppelklicken (oder `Starten.command`)
   - **Windows:** `Starten.bat` doppelklicken (oder `python server.py` im Terminal)
   - **Linux:** `python3 server.py` im Terminal
3. Im Browser öffnet sich automatisch `http://localhost:7321`

Benötigte Abhängigkeiten (Flask, yt-dlp, faster-whisper) werden beim ersten Start automatisch installiert.

### Voraussetzungen
- Python 3
- [ffmpeg](https://ffmpeg.org/) (für Audio-/Video-Konvertierung) – muss im `PATH` verfügbar sein
  - macOS: `brew install ffmpeg`
  - Windows: [ffmpeg.org](https://ffmpeg.org/download.html) herunterladen und zum `PATH` hinzufügen
  - Linux: `sudo apt install ffmpeg` (oder entsprechendes Paket der Distribution)

---

## Feedback-Formular einrichten (optional)

1. Eigenen Telegram-Bot über [@BotFather](https://t.me/BotFather) erstellen → Bot-Token notieren
2. Dem Bot eine Nachricht schreiben, dann die Chat-ID über `https://api.telegram.org/bot<TOKEN>/getUpdates` ermitteln
3. `feedback_config.example.json` zu `feedback_config.json` kopieren und Token + Chat-ID eintragen

```json
{
  "telegram_bot_token": "DEIN_TELEGRAM_BOT_TOKEN",
  "telegram_chat_id": "DEINE_TELEGRAM_CHAT_ID"
}
```

`feedback_config.json` ist in `.gitignore` enthalten und wird nicht mit hochgeladen.

---

## Datenschutz

Alles läuft lokal auf deinem Computer. Es werden keine Daten an Dritte gesendet (außer optional dein eigenes Feedback an deinen eigenen Telegram-Bot).

---

© Molschder-Bub 2026 · Vers. 1.6
