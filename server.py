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
APP_VERSION = "1.6"

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
<link rel="icon" type="image/x-icon" href="data:image/x-icon;base64,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">
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
  .brand-mark-img {
    width: 32px; height: 32px;
    border-radius: 9px;
    flex-shrink: 0;
    object-fit: cover;
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
  mark.ts-hit {
    background: #facc15;
    color: #1a1a1a;
    border-radius: 3px;
    padding: 1px 3px;
    font-weight: 600;
  }
  mark.ts-hit.ts-active {
    background: var(--accent);
    color: #fff;
    border-radius: 3px;
    padding: 1px 3px;
  }

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
      <img class="brand-mark-img" src="data:image/png;base64,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" alt="Roland">
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
    // File is already ready – show download button and auto-trigger immediately
    if (data.filename && !document.getElementById('downloadBtn').innerHTML) {
      document.getElementById('downloadBtn').innerHTML =
        `<a class="btn-download" href="/download/${jobId}">⬇ ${data.filename}</a>`;
      const autoLink = document.createElement('a');
      autoLink.href = `/download/${jobId}`;
      autoLink.download = data.filename;
      document.body.appendChild(autoLink);
      autoLink.click();
      autoLink.remove();
    }
  } else if (data.status === 'done') {
    clearInterval(pollInterval);
    document.getElementById('progressBar').style.width = '100%';
    document.getElementById('progressText').textContent = 'Fertig!';
    // Show download button if not already shown (e.g. no transcription)
    if (!document.getElementById('downloadBtn').innerHTML) {
      document.getElementById('downloadBtn').innerHTML =
        `<a class="btn-download" href="/download/${jobId}">⬇ ${data.filename}</a>`;
      const autoLink = document.createElement('a');
      autoLink.href = `/download/${jobId}`;
      autoLink.download = data.filename;
      document.body.appendChild(autoLink);
      autoLink.click();
      autoLink.remove();
    }
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
    // Compute offset relative to the scroll container
    const boxTop  = scrollBox.getBoundingClientRect().top;
    const elTop   = el.getBoundingClientRect().top;
    const target  = scrollBox.scrollTop + (elTop - boxTop) - 16;
    scrollBox.scrollTo({ top: Math.max(target, 0), behavior: 'smooth' });
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
    if not job or not job.get("filepath") or job["status"] not in ("done", "transcribing"):
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
        is_twitter = any(h in url for h in ("twitter.com", "x.com", "t.co"))

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

        # Twitter/X requires browser cookies since API changes in 2023.
        # Use Chrome with "basic" keyring to avoid macOS Keychain prompt,
        # then Safari as fallback, then no cookies as last resort.
        if is_twitter:
            last_exc = None
            for cookie_src in (
                ("chrome", None, "basic", None),  # Chrome, no Keychain prompt
                ("safari",),                       # Safari fallback
            ):
                try:
                    browser_opts = dict(opts, cookiesfrombrowser=cookie_src)
                    with yt_dlp.YoutubeDL(browser_opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                    last_exc = None
                    break
                except Exception as ex:
                    last_exc = ex
                    continue
            if last_exc is not None:
                # Last resort: no cookies
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
            job["title"] = info.get("title", "Download")
        else:
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
        err = str(e)
        # Benutzerfreundliche Fehlermeldungen
        if "No video could be found" in err:
            err = "In diesem Beitrag wurde kein Video gefunden. Bitte prüfe, ob der Link ein Video enthält."
        elif "Private video" in err or "This video is private" in err:
            err = "Dieses Video ist privat und kann nicht heruntergeladen werden."
        elif "members-only" in err or "member-only" in err:
            err = "Dieses Video ist nur für Mitglieder verfügbar."
        elif "copyright" in err.lower():
            err = "Dieses Video ist aus urheberrechtlichen Gründen nicht verfügbar."
        elif "404" in err or "not found" in err.lower():
            err = "Der Beitrag wurde nicht gefunden. Möglicherweise wurde er gelöscht oder ist nicht öffentlich."
        elif "429" in err or "Too Many Requests" in err:
            err = "Zu viele Anfragen – bitte kurz warten und erneut versuchen."
        job["error"] = err


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
