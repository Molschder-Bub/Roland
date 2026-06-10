#!/bin/bash
# Roland launcher – startet den lokalen Server und öffnet den Browser
APP_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"
PROJECT_DIR="$APP_DIR"

# Ensure Homebrew tools (ffmpeg) are reachable
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

cd "$PROJECT_DIR"
# Force native Apple-Silicon (arm64) execution so binary extensions
# (e.g. for the transcription feature) match the installed libraries.
exec arch -arm64 /usr/bin/python3 "$PROJECT_DIR/server.py" >/tmp/roland.log 2>&1
