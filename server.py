#!/usr/bin/env python3
"""Roland – lokaler Download-Server"""

import os
import sys
import threading
import subprocess

# Make sure Homebrew binaries (ffmpeg etc.) are found even when launched
# via double-click, where /opt/homebrew/bin is not on PATH.
for _p in ("/opt/homebrew/bin", "/usr/local/bin"):
    if _p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _p + os.pathsep + os.environ.get("PATH", "")

# Auto-install dependencies
def install(pkg):
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", pkg],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

try:
    import flask
except ImportError:
    install("flask")
    import flask

try:
    import yt_dlp
except ImportError:
    install("yt-dlp")
    import yt_dlp

# Optional: speech-to-text transcription (loaded lazily on first use)
_whisper_model = None
_whisper_lock = threading.Lock()

def get_whisper_model():
    """Lazily load the faster-whisper model (only once, thread-safe)."""
    global _whisper_model
    with _whisper_lock:
        if _whisper_model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError:
                install("faster-whisper")
                from faster_whisper import WhisperModel
            # "small" = good balance of speed/accuracy on CPU; auto language detection
            _whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
        return _whisper_model

from flask import Flask, request, jsonify, send_file, render_template_string
import json
import tempfile
import uuid
import time
import urllib.request
import urllib.parse
import urllib.error

app = Flask(__name__)

DOWNLOAD_DIR = os.path.join(tempfile.gettempdir(), "roland_downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Feedback (Telegram bot) config
# ---------------------------------------------------------------------------
FEEDBACK_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feedback_config.json")

def load_feedback_config():
    try:
        with open(FEEDBACK_CONFIG_PATH, "r") as f:
            cfg = json.load(f)
        return cfg.get("telegram_bot_token", "").strip(), cfg.get("telegram_chat_id", "").strip()
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return "", ""

jobs = {}  # job_id -> {status, progress, filename, filepath, error}

# ---------------------------------------------------------------------------
# App version
# ---------------------------------------------------------------------------
# WICHTIG: Bei jeder funktionalen Änderung an Roland muss diese Versionsnummer
# erhoeht werden (z.B. "beta 0.1" -> "beta 0.2"). Wird im Footer angezeigt.
APP_VERSION = "beta 0.2"

# ---------------------------------------------------------------------------
# Copyright / Footer
# ---------------------------------------------------------------------------
# GESCHUETZT – NICHT ENTFERNEN ODER AENDERN.
# Dieser Hinweis erscheint im Footer der Oberflaeche und darf beim
# Veroeffentlichen (z.B. auf GitHub) oder bei zukuenftigen Aenderungen
# nicht geloescht oder umbenannt werden.
APP_COPYRIGHT_HOLDER = "Molschder-Bub"
APP_COPYRIGHT_YEAR = "2026"

# ---------------------------------------------------------------------------
# Supported platforms info
# ---------------------------------------------------------------------------
PLATFORMS = [
    {"name": "YouTube",     "icon": "▶️",  "color": "#FF5A5F", "url": "https://www.youtube.com"},
    {"name": "X / Twitter", "icon": "𝕏",  "color": "#5AA9E6", "url": "https://x.com"},
    {"name": "Instagram",   "icon": "📸", "color": "#E07A9C", "url": "https://www.instagram.com"},
    {"name": "TikTok",      "icon": "🎵", "color": "#5BC8C2", "url": "https://www.tiktok.com"},
    {"name": "Facebook",    "icon": "👍", "color": "#6C9BCF", "url": "https://www.facebook.com"},
    {"name": "Vimeo",       "icon": "🎥", "color": "#7FCDCD", "url": "https://vimeo.com"},
    {"name": "SoundCloud",  "icon": "☁️",  "color": "#FFB37B", "url": "https://soundcloud.com"},
    {"name": "Reddit",      "icon": "👽", "color": "#FF8966", "url": "https://www.reddit.com"},
    {"name": "Twitch",      "icon": "🎮", "color": "#B49AE0", "url": "https://www.twitch.tv"},
]

# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
HTML = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Roland</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    /* Sidebar */
    --sb-bg:     #111113;
    --sb-border: #222226;
    --sb-text:   #e4e4e7;
    --sb-muted:  #52525b;
    --sb-hover:  #1c1c1f;
    --sb-accent: #a78bfa;
    /* Main */
    --bg:        #f4f4f5;
    --card:      #ffffff;
    --border:    #e4e4e7;
    --accent:    #6366f1;
    --accent-h:  #4f46e5;
    --accent2:   #06b6d4;
    --success:   #16a34a;
    --error:     #dc2626;
    --text:      #18181b;
    --text2:     #52525b;
    --text3:     #a1a1aa;
    --radius-sm: 8px;
    --radius:    12px;
    --radius-lg: 16px;
    --shadow-sm: 0 1px 3px rgba(0,0,0,.08), 0 1px 2px rgba(0,0,0,.05);
    --shadow:    0 4px 16px rgba(0,0,0,.08), 0 2px 6px rgba(0,0,0,.05);
    --shadow-lg: 0 12px 40px rgba(0,0,0,.10), 0 4px 12px rgba(0,0,0,.06);
  }

  html, body { height: 100%; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', sans-serif;
    font-size: 15px;
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
  }

  /* ── Shell ──────────────────────────────── */
  .shell { display: flex; min-height: 100vh; }

  /* ── Sidebar ────────────────────────────── */
  .sidebar {
    width: 252px;
    flex-shrink: 0;
    background: var(--sb-bg);
    border-right: 1px solid var(--sb-border);
    display: flex;
    flex-direction: column;
    padding: 0;
    position: sticky;
    top: 0;
    height: 100vh;
    overflow-y: auto;
  }

  .sidebar-brand {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 20px 20px 0;
    margin-bottom: 28px;
  }
  .brand-mark {
    width: 32px; height: 32px;
    border-radius: 9px;
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    display: flex; align-items: center; justify-content: center;
    font-size: 15px; font-weight: 800; color: #fff;
    flex-shrink: 0;
    letter-spacing: -0.5px;
  }
  .brand-name {
    font-size: 17px;
    font-weight: 700;
    color: var(--sb-text);
    letter-spacing: -0.3px;
  }

  .sidebar-section { padding: 0 12px; margin-bottom: 28px; }
  .sidebar-label {
    font-size: 11px;
    font-weight: 600;
    color: var(--sb-muted);
    text-transform: uppercase;
    letter-spacing: 1.2px;
    padding: 0 8px;
    margin-bottom: 8px;
  }

  .platform-list { display: flex; flex-direction: column; gap: 2px; }
  .platform-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 7px 8px;
    border-radius: var(--radius-sm);
    font-size: 13px;
    font-weight: 500;
    color: var(--sb-text);
    text-decoration: none;
    opacity: .75;
    cursor: pointer;
    transition: background .15s, opacity .15s;
  }
  .platform-item:hover { background: var(--sb-hover); opacity: 1; }
  .platform-logo {
    width: 22px; height: 22px;
    border-radius: 6px;
    display: flex; align-items: center; justify-content: center;
    font-size: 13px;
    flex-shrink: 0;
  }

  .feature-list { display: flex; flex-direction: column; gap: 2px; }
  .feature-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 6px 8px;
    border-radius: var(--radius-sm);
    font-size: 13px;
    color: var(--sb-text);
    opacity: .75;
  }
  .feature-item span:first-child { font-size: 14px; flex-shrink: 0; width: 20px; text-align: center; }

  .sidebar-footer {
    margin-top: auto;
    padding: 16px 20px;
    border-top: 1px solid var(--sb-border);
    font-size: 11.5px;
    color: var(--sb-muted);
    line-height: 1.6;
  }
  .sidebar-footer strong { color: #71717a; font-weight: 600; }

  /* ── Feedback card ──────────────────────── */
  .feedback-card {
    margin-top: 16px;
    max-width: 720px;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow);
    overflow: hidden;
  }
  .feedback-toggle {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 14px 20px;
    cursor: pointer;
    user-select: none;
    transition: background .12s;
  }
  .feedback-toggle:hover { background: var(--bg); }
  .feedback-card:not(.collapsed) .feedback-toggle {
    border-bottom: 1px solid var(--border);
  }
  .feedback-chevron {
    color: var(--text3);
    font-size: 11px;
    transition: transform .2s;
    flex-shrink: 0;
    line-height: 1;
  }
  .feedback-card.collapsed .feedback-chevron { transform: rotate(-90deg); }
  .feedback-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--text);
  }
  .feedback-body {
    padding: 16px 20px 20px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .feedback-card.collapsed .feedback-body { display: none; }
  .feedback-body input,
  .feedback-body textarea {
    border: 1.5px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 9px 12px;
    font-size: 14px;
    font-family: inherit;
    color: var(--text);
    background: var(--bg);
    outline: none;
    resize: vertical;
    transition: border-color .15s;
  }
  .feedback-body input:focus,
  .feedback-body textarea:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px rgba(99,102,241,.10);
  }
  .feedback-footer {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 14px;
  }
  .modal-status {
    font-size: 12.5px;
  }
  .modal-status.error { color: var(--error); }
  .modal-status.success { color: var(--success); }

  /* ── Main ───────────────────────────────── */
  .main {
    flex: 1;
    min-width: 0;
    padding: 48px 52px 64px;
    display: flex;
    flex-direction: column;
  }

  .page-header { margin-bottom: 36px; }
  .page-title {
    font-size: 26px;
    font-weight: 700;
    color: var(--text);
    letter-spacing: -0.5px;
    line-height: 1.2;
    margin-bottom: 6px;
  }
  .page-sub {
    font-size: 14px;
    color: var(--text2);
  }

  /* ── Input card ─────────────────────────── */
  .input-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 20px;
    box-shadow: var(--shadow);
    max-width: 720px;
  }
  .app-copyright {
    max-width: 720px;
    text-align: center;
    font-size: 11.5px;
    color: var(--text3);
    margin-top: 8px;
  }

  /* URL row */
  .url-row {
    display: flex;
    align-items: center;
    gap: 8px;
    background: var(--bg);
    border: 1.5px solid var(--border);
    border-radius: var(--radius);
    padding: 0 6px 0 14px;
    transition: border-color .15s, box-shadow .15s;
  }
  .url-row:focus-within {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px rgba(99,102,241,.12);
  }
  .url-icon { color: var(--text3); flex-shrink: 0; }
  .url-row input {
    flex: 1;
    border: none;
    outline: none;
    background: transparent;
    font-size: 14.5px;
    color: var(--text);
    padding: 13px 8px;
    min-width: 0;
  }
  .url-row input::placeholder { color: var(--text3); }
  .clear-btn {
    display: none;
    align-items: center;
    justify-content: center;
    width: 26px; height: 26px;
    border-radius: 50%;
    border: none;
    background: var(--border);
    color: var(--text2);
    font-size: 13px;
    cursor: pointer;
    flex-shrink: 0;
    transition: background .15s, color .15s;
  }
  .clear-btn.show { display: inline-flex; }
  .clear-btn:hover { background: #d4d4d8; color: var(--text); }

  /* Controls row */
  .controls-row {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-top: 12px;
    flex-wrap: wrap;
  }
  .ctrl-group { display: flex; flex-direction: column; gap: 4px; }
  .ctrl-label {
    font-size: 11px;
    font-weight: 600;
    color: var(--text3);
    text-transform: uppercase;
    letter-spacing: .8px;
    padding-left: 2px;
  }
  .ctrl-select {
    border: 1.5px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--bg);
    color: var(--text);
    font-size: 13.5px;
    font-weight: 500;
    padding: 7px 34px 7px 12px;
    cursor: pointer;
    outline: none;
    -webkit-appearance: none;
    appearance: none;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'%3E%3Cpath d='M1 1l5 5 5-5' fill='none' stroke='%23a1a1aa' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
    background-repeat: no-repeat;
    background-position: right 10px center;
    background-size: 11px;
    transition: border-color .15s;
  }
  .ctrl-select:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(99,102,241,.1); }
  .ctrl-select option { background: #fff; color: #18181b; }
  #qualitySelect { display: none; }
  #qualitySelect.show { display: block; }

  .transcribe-toggle {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: var(--text2);
    cursor: pointer;
    user-select: none;
    margin-left: 4px;
    flex-shrink: 0;
  }
  .transcribe-toggle input { accent-color: var(--accent); width: 15px; height: 15px; cursor: pointer; }

  .btn-go {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 9px 20px;
    background: var(--accent);
    color: #fff;
    border: none;
    border-radius: var(--radius-sm);
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: background .15s, transform .1s;
    white-space: nowrap;
    flex-shrink: 0;
  }
  .btn-go:hover { background: var(--accent-h); }
  .btn-go:active { transform: scale(.97); }

  /* ── Result card ────────────────────────── */
  .result-wrap { margin-top: 20px; max-width: 720px; display: none; }
  .result-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 24px 24px 20px;
    box-shadow: var(--shadow);
  }
  .result-meta {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 18px;
  }
  .result-label {
    font-size: 11px;
    font-weight: 600;
    color: var(--text3);
    text-transform: uppercase;
    letter-spacing: .8px;
    margin-bottom: 4px;
  }
  .video-title {
    font-size: 15px;
    font-weight: 600;
    color: var(--text);
    line-height: 1.4;
  }
  .result-close {
    width: 28px; height: 28px;
    flex-shrink: 0;
    border: 1px solid var(--border);
    background: var(--bg);
    color: var(--text2);
    border-radius: 6px;
    cursor: pointer;
    font-size: 13px;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background .12s, color .12s, border-color .12s;
  }
  .result-close:hover { background: var(--error); color: #fff; border-color: var(--error); }
  .progress-bar-wrap {
    background: var(--bg);
    border-radius: 99px;
    height: 5px;
    overflow: hidden;
    margin-bottom: 7px;
  }
  .progress-bar {
    height: 100%;
    width: 0%;
    background: linear-gradient(90deg, var(--accent), var(--accent2));
    transition: width .4s ease;
    border-radius: 99px;
  }
  .progress-text {
    font-size: 12.5px;
    color: var(--text3);
    margin-bottom: 18px;
    min-height: 18px;
    display: flex;
    align-items: center;
    gap: 7px;
  }
  #downloadBtn a.btn-download {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 11px 22px;
    background: var(--success);
    color: #fff;
    border-radius: var(--radius-sm);
    font-size: 14px;
    font-weight: 600;
    text-decoration: none;
    transition: opacity .15s, transform .1s;
  }
  #downloadBtn a.btn-download:hover { opacity: .88; }
  #downloadBtn a.btn-download:active { transform: scale(.97); }
  .error-msg {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    color: var(--error);
    font-size: 13.5px;
    background: #fef2f2;
    border: 1px solid #fecaca;
    border-radius: var(--radius-sm);
    padding: 10px 14px;
    margin-top: 8px;
  }
  .error-msg:empty { display: none; }

  .spinner {
    display: inline-block;
    width: 14px; height: 14px;
    border: 2px solid rgba(0,0,0,.10);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin .7s linear infinite;
    flex-shrink: 0;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* ── Transcript ─────────────────────────── */
  .transcript-box {
    margin-top: 16px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    display: none;
    flex-direction: column;
    background: var(--card);
  }
  .transcript-box.show { display: flex; }

  .transcript-header { flex-shrink: 0; }

  .transcript-toggle-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 14px;
    cursor: pointer;
    user-select: none;
    border-bottom: 1px solid var(--border);
    transition: background .12s;
  }
  .transcript-toggle-row:hover { background: var(--bg); }

  .transcript-chevron {
    color: var(--text3);
    font-size: 11px;
    transition: transform .2s;
    flex-shrink: 0;
    line-height: 1;
  }
  .transcript-box.collapsed .transcript-chevron { transform: rotate(-90deg); }

  .transcript-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--text);
    flex: 1;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .transcript-save {
    display: flex;
    align-items: center;
    gap: 5px;
    font-size: 12px;
    font-weight: 500;
    color: var(--text2);
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 5px 11px;
    cursor: pointer;
    transition: background .12s, color .12s, border-color .12s;
  }
  .transcript-save:hover { background: var(--accent); color: #fff; border-color: var(--accent); }

  .transcript-body {
    display: flex;
    flex-direction: column;
    min-height: 0;
    flex: 1;
  }
  .transcript-box.collapsed .transcript-body { display: none; }

  .transcript-search {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 12px;
    border-bottom: 1px solid var(--border);
    background: var(--bg);
    flex-shrink: 0;
  }
  .transcript-search input {
    flex: 1;
    border: 1.5px solid var(--border);
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 13px;
    color: var(--text);
    background: var(--card);
    outline: none;
    min-width: 0;
    transition: border-color .15s;
  }
  .transcript-search input:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px rgba(99,102,241,.10);
  }
  .ts-count {
    font-size: 12px;
    color: var(--text3);
    white-space: nowrap;
    min-width: 52px;
    text-align: right;
  }
  .transcript-search button {
    width: 28px; height: 28px;
    border: 1px solid var(--border);
    background: var(--card);
    color: var(--text2);
    border-radius: 6px;
    cursor: pointer;
    font-size: 13px;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background .12s, color .12s, border-color .12s;
    flex-shrink: 0;
  }
  .transcript-search button:hover { background: var(--accent); color: #fff; border-color: var(--accent); }
  .transcript-search button:disabled { opacity: .35; cursor: default; background: var(--card); color: var(--text3); border-color: var(--border); }
  .ts-clear { display: none; }
  .ts-clear.show { display: flex; }

  .transcript-scroll {
    overflow-y: scroll;
    max-height: 380px;
    padding: 14px 16px;
    scrollbar-gutter: stable;
    scrollbar-width: auto;
    scrollbar-color: var(--text3) var(--card);
  }
  .transcript-scroll::-webkit-scrollbar {
    width: 12px;
  }
  .transcript-scroll::-webkit-scrollbar-track {
    background: var(--card);
    border-radius: 8px;
  }
  .transcript-scroll::-webkit-scrollbar-thumb {
    background-color: var(--text3);
    border-radius: 8px;
    border: 3px solid var(--card);
  }
  .transcript-scroll::-webkit-scrollbar-thumb:hover {
    background-color: var(--text2);
  }
  .transcript-ts {
    display: inline-block;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 11px;
    font-weight: 600;
    color: var(--accent2);
    background: rgba(6,182,212,.09);
    border-radius: 4px;
    padding: 1px 6px;
    margin-right: 8px;
    letter-spacing: .1px;
  }
  #transcriptText { font-size: 13.5px; line-height: 1.75; color: var(--text); white-space: pre-wrap; }
  #transcriptText div { margin-bottom: 3px; }
  mark.ts-hit { background: #fef08a; color: inherit; border-radius: 3px; padding: 0 2px; }
  mark.ts-hit.ts-active { background: var(--accent); color: #fff; }

  /* ── Responsive ─────────────────────────── */
  @media (max-width: 900px) {
    .shell { flex-direction: column; }
    .sidebar { width: 100%; height: auto; position: relative; flex-direction: row; flex-wrap: wrap; padding: 16px; gap: 16px; }
    .sidebar-brand { margin-bottom: 0; }
    .sidebar-section { padding: 0; margin-bottom: 0; }
    .sidebar-footer { display: none; }
    .main { padding: 24px 20px 40px; }
  }
</style>
</head>
<body>

<div class="shell">

  <!-- ── Sidebar ───────────────────────────── -->
  <nav class="sidebar">
    <div class="sidebar-brand">
      <div class="brand-mark">R</div>
      <span class="brand-name">Roland</span>
    </div>

    <div class="sidebar-section">
      <div class="sidebar-label">Plattformen</div>
      <div class="platform-list" id="platformGrid"></div>
    </div>

    <div class="sidebar-section">
      <div class="sidebar-label">Features</div>
      <div class="feature-list">
        <div class="feature-item"><span>🎵</span><span>MP3 / M4A bis 320 kbps</span></div>
        <div class="feature-item"><span>🎬</span><span>MP4 / WebM, bis 4K</span></div>
        <div class="feature-item"><span>📝</span><span>Transkript mit Zeitmarken</span></div>
        <div class="feature-item"><span>🔒</span><span>100 % lokal, kein Upload</span></div>
        <div class="feature-item"><span>⚡</span><span>Live-Fortschritt</span></div>
      </div>
    </div>

    <div class="sidebar-footer">
      <strong>Lokal & privat</strong><br>
      Alles läuft auf deinem Computer.<br>
      Keine Daten verlassen deinen Computer.
    </div>
  </nav>

  <!-- ── Main ─────────────────────────────── -->
  <main class="main">
    <div class="page-header">
      <h1 class="page-title">Medien herunterladen</h1>
      <p class="page-sub">YouTube, X, Instagram, TikTok und mehr – direkt auf deinen PC</p>
    </div>

    <!-- Input card -->
    <div class="input-card">
      <div class="url-row">
        <svg class="url-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71"/></svg>
        <input id="urlInput" type="text" placeholder="URL einfügen – YouTube, X, Instagram, TikTok …" autocomplete="off">
        <button type="button" class="clear-btn" id="clearBtn" title="Eingabe löschen" onclick="clearUrl()">✕</button>
      </div>

      <div class="controls-row">
        <div class="ctrl-group">
          <span class="ctrl-label">Format</span>
          <select id="formatSelect" class="ctrl-select">
            <option value="mp3">MP3</option>
            <option value="mp4">MP4</option>
            <option value="m4a">M4A</option>
            <option value="webm">WebM</option>
          </select>
        </div>
        <div class="ctrl-group">
          <span class="ctrl-label">Auflösung</span>
          <select id="qualitySelect" class="ctrl-select">
            <option value="best">Beste</option>
            <option value="2160">4K</option>
            <option value="1440">1440p</option>
            <option value="1080" selected>1080p</option>
            <option value="720">720p</option>
            <option value="480">480p</option>
            <option value="360">360p</option>
          </select>
        </div>
        <label class="transcribe-toggle">
          <input type="checkbox" id="transcribeCheck">
          Transkript erstellen
        </label>
        <button class="btn-go" onclick="startDownload()">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          Herunterladen
        </button>
      </div>
    </div>
    <!-- Feedback -->
    <div class="feedback-card collapsed" id="feedbackCard">
      <div class="feedback-toggle" id="feedbackToggle">
        <span class="feedback-chevron" id="feedbackChevron">▾</span>
        <div class="feedback-title">💬 Feedback geben</div>
      </div>
      <div class="feedback-body" id="feedbackBody">
        <input type="text" id="feedbackName" placeholder="Dein Name (optional)" autocomplete="off">
        <textarea id="feedbackMessage" rows="3" placeholder="Was möchtest du uns mitteilen?"></textarea>
        <div class="feedback-footer">
          <div class="modal-status" id="feedbackStatus"></div>
          <button type="button" class="btn-go" id="feedbackSend">Senden</button>
        </div>
      </div>
    </div>
    <!--
      GESCHUETZT – NICHT ENTFERNEN ODER AENDERN.
      Copyright-Hinweis & Versionsangabe (siehe APP_COPYRIGHT_HOLDER /
      APP_COPYRIGHT_YEAR / APP_VERSION in server.py).
    -->
    <div class="app-copyright">© {{ copyright_holder }} {{ copyright_year }} · Vers. {{ app_version }}</div>

    <!-- Result -->
    <div class="result-wrap" id="resultWrap">
      <div class="result-card">
        <div class="result-meta">
          <div>
            <div class="result-label">Download</div>
            <div class="video-title" id="videoTitle">–</div>
          </div>
          <button type="button" class="result-close" id="resultClose" title="Schließen">✕</button>
        </div>
        <div class="progress-bar-wrap"><div class="progress-bar" id="progressBar"></div></div>
        <div class="progress-text" id="progressText">Warte …</div>
        <div id="downloadBtn"></div>
        <div class="error-msg" id="errorMsg"></div>

        <!-- Transcript -->
        <div class="transcript-box" id="transcriptBox">
          <div class="transcript-header">
            <div class="transcript-toggle-row" id="transcriptToggle">
              <span class="transcript-chevron" id="transcriptChevron">▾</span>
              <div class="transcript-title">📝 Transkript</div>
              <button type="button" class="transcript-save" id="transcriptSave">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                Speichern
              </button>
            </div>
            <div class="transcript-body" id="transcriptBody">
              <div class="transcript-search">
                <input type="text" id="transcriptSearch" placeholder="Suchen …" autocomplete="off">
                <button type="button" class="ts-clear" id="tsClear" title="Suche löschen">✕</button>
                <span class="ts-count" id="tsCount"></span>
                <button type="button" id="tsPrev" title="Vorheriger Treffer">↑</button>
                <button type="button" id="tsNext" title="Nächster Treffer">↓</button>
              </div>
              <div class="transcript-scroll" id="transcriptScroll">
                <div id="transcriptText"></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </main>

</div>

<script>
const PLATFORMS = {{ platforms|tojson }};

// Render platforms in sidebar
const grid = document.getElementById('platformGrid');
PLATFORMS.forEach(p => {
  const el = document.createElement('a');
  el.className = 'platform-item';
  el.href = p.url;
  el.target = '_blank';
  el.rel = 'noopener noreferrer';
  el.title = `${p.name} öffnen`;
  el.innerHTML = `<span class="platform-logo" style="background:${p.color}">${p.icon}</span>${p.name}`;
  grid.appendChild(el);
});

// Enter key
const urlInputEl = document.getElementById('urlInput');
const clearBtnEl = document.getElementById('clearBtn');
urlInputEl.addEventListener('keydown', e => {
  if (e.key === 'Enter') startDownload();
});

// Show/hide clear ("x") button depending on whether the field has content
function syncClearBtn() {
  if (urlInputEl.value.trim().length > 0) {
    clearBtnEl.classList.add('show');
  } else {
    clearBtnEl.classList.remove('show');
  }
}
urlInputEl.addEventListener('input', syncClearBtn);
syncClearBtn();

function clearUrl() {
  urlInputEl.value = '';
  syncClearBtn();
  urlInputEl.focus();
}

// Show quality selector only for video formats
const formatSelect  = document.getElementById('formatSelect');
const qualitySelect = document.getElementById('qualitySelect');
function syncQualityVisibility() {
  if (formatSelect.value === 'mp4' || formatSelect.value === 'webm') {
    qualitySelect.classList.add('show');
  } else {
    qualitySelect.classList.remove('show');
  }
}
formatSelect.addEventListener('change', syncQualityVisibility);
syncQualityVisibility();

let pollInterval = null;

async function startDownload() {
  const url        = document.getElementById('urlInput').value.trim();
  const format     = document.getElementById('formatSelect').value;
  const quality    = document.getElementById('qualitySelect').value;
  const transcribe = document.getElementById('transcribeCheck').checked;
  if (!url) { alert('Bitte eine URL eingeben.'); return; }

  // Reset UI
  clearInterval(pollInterval);
  document.getElementById('resultWrap').style.display = 'block';
  document.getElementById('videoTitle').textContent   = 'Analysiere URL …';
  document.getElementById('progressBar').style.width  = '0%';
  document.getElementById('progressText').innerHTML   = '<span class="spinner"></span> Starte …';
  document.getElementById('downloadBtn').innerHTML    = '';
  document.getElementById('errorMsg').textContent     = '';
  document.getElementById('transcriptBox').classList.remove('show');
  document.getElementById('transcriptBox').classList.remove('collapsed');
  document.getElementById('transcriptText').textContent = '';
  document.getElementById('transcriptSearch').value = '';
  document.getElementById('tsCount').textContent = '';
  syncTsClearBtn();
  currentTranscript = ''; tsMatches = []; tsActive = -1;
  document.getElementById('resultWrap').scrollIntoView({behavior:'smooth'});

  const res  = await fetch('/start', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({url, format, quality, transcribe})
  });
  const data = await res.json();
  if (!data.job_id) { showError(data.error || 'Unbekannter Fehler'); return; }

  // Clear the field right away so the next URL can be pasted immediately
  clearUrl();

  pollInterval = setInterval(() => poll(data.job_id), 800);
}

document.getElementById('resultClose').addEventListener('click', () => {
  clearInterval(pollInterval);
  document.getElementById('resultWrap').style.display = 'none';
  document.getElementById('videoTitle').textContent   = '–';
  document.getElementById('progressBar').style.width  = '0%';
  document.getElementById('progressText').textContent = '';
  document.getElementById('downloadBtn').innerHTML    = '';
  document.getElementById('errorMsg').textContent     = '';
  document.getElementById('transcriptBox').classList.remove('show');
  document.getElementById('transcriptBox').classList.remove('collapsed');
  document.getElementById('transcriptText').textContent = '';
  document.getElementById('transcriptSearch').value = '';
  document.getElementById('tsCount').textContent = '';
  syncTsClearBtn();
  currentTranscript = ''; tsMatches = []; tsActive = -1;
});

async function poll(jobId) {
  const res  = await fetch(`/status/${jobId}`);
  const data = await res.json();

  if (data.title) document.getElementById('videoTitle').textContent = data.title;

  if (data.status === 'downloading') {
    const pct = data.percent || 0;
    document.getElementById('progressBar').style.width = pct + '%';
    document.getElementById('progressText').textContent =
      `Lade herunter … ${pct.toFixed(1)}%  ${data.speed || ''}`;
  } else if (data.status === 'processing') {
    document.getElementById('progressBar').style.width = '95%';
    document.getElementById('progressText').textContent = 'Konvertiere …';
  } else if (data.status === 'transcribing') {
    document.getElementById('progressBar').style.width = '98%';
    document.getElementById('progressText').innerHTML =
      '<span class="spinner"></span> Transkribiere Inhalt … (kann je nach Länge etwas dauern)';
  } else if (data.status === 'done') {
    clearInterval(pollInterval);
    document.getElementById('progressBar').style.width = '100%';
    document.getElementById('progressText').textContent = 'Fertig!';
    document.getElementById('downloadBtn').innerHTML =
      `<a class="btn-download" href="/download/${jobId}">⬇ ${data.filename}</a>`;
    if (data.transcript) {
      renderTranscript(data.transcript);
      document.getElementById('transcriptBox').classList.add('show');
    }
  } else if (data.status === 'error') {
    clearInterval(pollInterval);
    showError(data.error);
  }
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

let currentTranscript = '';
let tsMatches  = [];
let tsActive   = -1;

function escapeRegExp(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// Render transcript lines, highlighting the leading "[hh:mm:ss – hh:mm:ss]" timestamp as
// a badge, and (if a search term is active) wrapping matches in <mark> for highlighting.
function renderTranscript(transcript) {
  currentTranscript = transcript || '';
  const box   = document.getElementById('transcriptText');
  const query = document.getElementById('transcriptSearch').value.trim();
  const lines = currentTranscript.split('\n');
  let matchCounter = 0;

  function highlightText(text) {
    if (!query) return escapeHtml(text);
    const re = new RegExp(escapeRegExp(query), 'gi');
    let result = '';
    let lastIndex = 0;
    let m;
    while ((m = re.exec(text)) !== null) {
      if (m[0].length === 0) { re.lastIndex++; continue; }
      result += escapeHtml(text.slice(lastIndex, m.index));
      result += `<mark class="ts-hit" data-idx="${matchCounter}">${escapeHtml(m[0])}</mark>`;
      matchCounter++;
      lastIndex = m.index + m[0].length;
    }
    result += escapeHtml(text.slice(lastIndex));
    return result;
  }

  const html = lines.map(line => {
    const m = line.match(/^\[([^\]]+)\]\s*(.*)$/);
    if (m) {
      return `<div><span class="transcript-ts">${escapeHtml(m[1])}</span>${highlightText(m[2])}</div>`;
    }
    return `<div>${highlightText(line)}</div>`;
  }).join('');
  box.innerHTML = html;

  tsMatches = Array.from(box.querySelectorAll('mark.ts-hit'));
  tsActive  = tsMatches.length ? 0 : -1;
  updateTsActive();
  updateTsCount();
}

function updateTsActive() {
  tsMatches.forEach((el, i) => el.classList.toggle('ts-active', i === tsActive));
  if (tsActive >= 0 && tsMatches[tsActive]) {
    const el        = tsMatches[tsActive];
    const scrollBox = document.getElementById('transcriptScroll');
    // Scroll within the (non-fixed) transcript area so the active hit lands
    // right at the top, just below the fixed title/search header.
    const target = el.offsetTop - 8;
    scrollBox.scrollTo({top: Math.max(target, 0), behavior: 'smooth'});
  }
}

function updateTsCount() {
  const countEl = document.getElementById('tsCount');
  const query   = document.getElementById('transcriptSearch').value.trim();
  if (!query) {
    countEl.textContent = '';
  } else if (tsMatches.length === 0) {
    countEl.textContent = 'Keine Treffer';
  } else {
    countEl.textContent = `${tsActive + 1} / ${tsMatches.length}`;
  }
  document.getElementById('tsPrev').disabled = tsMatches.length === 0;
  document.getElementById('tsNext').disabled = tsMatches.length === 0;
}

function tsGoTo(delta) {
  if (!tsMatches.length) return;
  tsActive = (tsActive + delta + tsMatches.length) % tsMatches.length;
  updateTsActive();
  updateTsCount();
}

const tsSearchInput = document.getElementById('transcriptSearch');
const tsClearBtn    = document.getElementById('tsClear');

function syncTsClearBtn() {
  tsClearBtn.classList.toggle('show', tsSearchInput.value.trim().length > 0);
}

tsSearchInput.addEventListener('input', () => { syncTsClearBtn(); renderTranscript(currentTranscript); });
tsSearchInput.addEventListener('keydown', e => {
  if (e.key === 'Enter') { e.preventDefault(); tsGoTo(e.shiftKey ? -1 : 1); }
});
tsClearBtn.addEventListener('click', () => {
  tsSearchInput.value = '';
  syncTsClearBtn();
  renderTranscript(currentTranscript);
  tsSearchInput.focus();
});
document.getElementById('tsPrev').addEventListener('click', () => tsGoTo(-1));
document.getElementById('tsNext').addEventListener('click', () => tsGoTo(1));

// Collapse / expand the whole transcript panel
document.getElementById('transcriptToggle').addEventListener('click', () => {
  document.getElementById('transcriptBox').classList.toggle('collapsed');
});

// Save the transcript as a local .txt file
document.getElementById('transcriptSave').addEventListener('click', e => {
  e.stopPropagation();
  if (!currentTranscript) return;
  const titleText = document.getElementById('videoTitle').textContent || 'Transkript';
  const safeName  = titleText.replace(/[\\/:*?"<>|]+/g, '').trim().slice(0, 120) || 'Transkript';
  const blob = new Blob([currentTranscript], {type: 'text/plain;charset=utf-8'});
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href = url;
  a.download = `${safeName} – Transkript.txt`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
});

function showError(msg) {
  document.getElementById('progressText').textContent = '';
  document.getElementById('errorMsg').textContent = '⚠ ' + msg;
}

// ── Feedback card ────────────────────────────
const feedbackCard   = document.getElementById('feedbackCard');
const feedbackStatus = document.getElementById('feedbackStatus');

document.getElementById('feedbackToggle').addEventListener('click', () => {
  feedbackCard.classList.toggle('collapsed');
});

document.getElementById('feedbackSend').addEventListener('click', async () => {
  const name    = document.getElementById('feedbackName').value.trim();
  const message = document.getElementById('feedbackMessage').value.trim();

  if (!message) {
    feedbackStatus.textContent = 'Bitte ein Feedback eingeben.';
    feedbackStatus.className = 'modal-status error';
    return;
  }

  feedbackStatus.textContent = 'Wird gesendet …';
  feedbackStatus.className = 'modal-status';

  try {
    const res  = await fetch('/feedback', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name, message})
    });
    const data = await res.json();
    if (data.ok) {
      feedbackStatus.textContent = 'Danke für dein Feedback! ✅';
      feedbackStatus.className = 'modal-status success';
      document.getElementById('feedbackName').value = '';
      document.getElementById('feedbackMessage').value = '';
      setTimeout(() => feedbackCard.classList.add('collapsed'), 1200);
    } else {
      feedbackStatus.textContent = '⚠ ' + (data.error || 'Unbekannter Fehler');
      feedbackStatus.className = 'modal-status error';
    }
  } catch (err) {
    feedbackStatus.textContent = '⚠ Verbindung fehlgeschlagen';
    feedbackStatus.className = 'modal-status error';
  }
});
</script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template_string(
        HTML,
        platforms=PLATFORMS,
        app_version=APP_VERSION,
        copyright_holder=APP_COPYRIGHT_HOLDER,
        copyright_year=APP_COPYRIGHT_YEAR,
    )


@app.route("/start", methods=["POST"])
def start():
    data   = request.get_json()
    url    = (data.get("url") or "").strip()
    fmt        = (data.get("format") or "mp3").lower()
    quality    = (data.get("quality") or "best").lower()
    transcribe = bool(data.get("transcribe"))
    if not url:
        return jsonify({"error": "Keine URL angegeben"}), 400

    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "starting", "percent": 0, "speed": "",
                    "title": "", "filename": "", "filepath": "", "error": "",
                    "transcript": ""}

    threading.Thread(target=run_download, args=(job_id, url, fmt, quality, transcribe), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/status/<job_id>")
def status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job nicht gefunden"}), 404
    return jsonify(job)


@app.route("/download/<job_id>")
def download(job_id):
    job = jobs.get(job_id)
    if not job or job["status"] != "done":
        return "Nicht bereit", 404
    return send_file(job["filepath"], as_attachment=True,
                     download_name=job["filename"])


@app.route("/feedback", methods=["POST"])
def feedback():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    message = (data.get("message") or "").strip()

    if not message:
        return jsonify({"error": "Bitte ein Feedback eingeben."}), 400

    token, chat_id = load_feedback_config()
    if not token or not chat_id:
        return jsonify({"error": "Telegram-Bot ist noch nicht konfiguriert (feedback_config.json)."}), 500

    text = f"📬 Neues Feedback für Roland\n\nVon: {name or 'Anonym'}\n\n{message}"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=payload, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
        if not resp_data.get("ok"):
            return jsonify({"error": f"Telegram-Fehler: {resp_data.get('description', 'unbekannt')}"}), 500
    except urllib.error.URLError as e:
        return jsonify({"error": f"Verbindung zu Telegram fehlgeschlagen: {e}"}), 500

    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Download worker
# ---------------------------------------------------------------------------

def run_download(job_id, url, fmt, quality="best", transcribe=False):
    job = jobs[job_id]
    out_dir = os.path.join(DOWNLOAD_DIR, job_id)
    os.makedirs(out_dir, exist_ok=True)

    has_ffmpeg = _check_ffmpeg()

    if fmt == "mp3":
        if has_ffmpeg:
            ydl_format = "bestaudio/best"
            postprocs  = [{"key": "FFmpegExtractAudio",
                           "preferredcodec": "mp3", "preferredquality": "320"}]
            ext        = "mp3"
        else:
            ydl_format = "bestaudio[ext=m4a]/bestaudio/best"
            postprocs  = []
            ext        = "m4a"
    elif fmt == "mp4":
        # Optional height cap, e.g. "1080" -> only formats with height<=1080
        h = "" if quality in ("", "best") else f"[height<={quality}]"
        if has_ffmpeg:
            ydl_format = (f"bestvideo{h}[ext=mp4]+bestaudio[ext=m4a]"
                          f"/best{h}[ext=mp4]/bestvideo{h}+bestaudio/best{h}/best")
        else:
            ydl_format = f"best{h}[ext=mp4]/best{h}/best"
        postprocs  = []
        ext        = "mp4"
    elif fmt == "m4a":
        ydl_format = "bestaudio[ext=m4a]/bestaudio/best"
        postprocs  = [{"key": "FFmpegExtractAudio", "preferredcodec": "m4a"}] if has_ffmpeg else []
        ext        = "m4a"
    else:  # webm
        h = "" if quality in ("", "best") else f"[height<={quality}]"
        ydl_format = f"bestvideo{h}[ext=webm]+bestaudio[ext=webm]/best{h}[ext=webm]/bestaudio[ext=webm]/best{h}/best"
        postprocs  = []
        ext        = "webm"

    def progress_hook(d):
        if d["status"] == "downloading":
            job["status"]  = "downloading"
            job["percent"] = float((d.get("downloaded_bytes") or 0) /
                                   max(d.get("total_bytes") or d.get("total_bytes_estimate") or 1, 1) * 100)
            job["speed"]   = d.get("_speed_str", "").strip()
            if not job["title"] and d.get("info_dict"):
                job["title"] = d["info_dict"].get("title", "")
        elif d["status"] == "finished":
            job["status"] = "processing"

    try:
        job["status"] = "downloading"
        opts = {
            "format": ydl_format,
            "outtmpl": os.path.join(out_dir, "%(title)s.%(ext)s"),
            "postprocessors": postprocs,
            "progress_hooks": [progress_hook],
            "quiet": True,
            "no_warnings": True,
            # Workaround for YouTube's "HTTP 403 Forbidden" on direct downloads:
            # the android player client returns URLs that don't require the
            # browser-style signature/cookie handshake.
            "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            job["title"] = info.get("title", "Download")

        # Find the output file
        for fname in os.listdir(out_dir):
            job["filepath"] = os.path.join(out_dir, fname)
            job["filename"] = fname
            break

        # Optional: transcribe spoken content to text (runs locally, no upload)
        if transcribe and job["filepath"]:
            try:
                job["status"] = "transcribing"
                model = get_whisper_model()
                segments, _info = model.transcribe(job["filepath"], beam_size=5)

                def fmt_ts(t):
                    h, rem = divmod(int(t), 3600)
                    m, s   = divmod(rem, 60)
                    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

                # Gruppiere einzelne Whisper-Segmente zu ~30-Sekunden-Abschnitten,
                # damit das Transkript besser lesbar ist (statt einer Zeile pro Satz).
                GROUP_SECONDS = 30
                lines = []
                group_start = None
                group_end = None
                group_texts = []

                def flush_group():
                    if group_texts:
                        text = " ".join(group_texts).strip()
                        if text:
                            lines.append(f"[{fmt_ts(group_start)} – {fmt_ts(group_end)}]  {text}")

                for seg in segments:
                    txt = seg.text.strip()
                    if not txt:
                        continue
                    if group_start is None:
                        group_start = seg.start
                    # Neue Gruppe beginnen, sobald die aktuelle ~30s erreicht hat
                    if group_end is not None and (seg.start - group_start) >= GROUP_SECONDS:
                        flush_group()
                        group_start = seg.start
                        group_texts = []
                    group_end = seg.end
                    group_texts.append(txt)

                flush_group()
                job["transcript"] = "\n".join(lines) or "(Kein Sprachinhalt erkannt)"
            except Exception as te:
                job["transcript"] = f"(Transkription fehlgeschlagen: {te})"

        job["status"] = "done"
    except Exception as e:
        job["status"] = "error"
        job["error"]  = str(e)


def _check_ffmpeg():
    try:
        subprocess.check_call(["ffmpeg", "-version"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import webbrowser
    port = 7321
    print(f"\n  Roland läuft auf http://localhost:{port}\n")
    threading.Timer(1.2, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    app.run(port=port, debug=False)
