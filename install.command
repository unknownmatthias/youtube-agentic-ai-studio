#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  🎬 YouTube AI Agent Studio — macOS installer
#
#  DOUBLE-CLICK THIS FILE (or right-click → Open) to install.
#  It is a thin wrapper: the real work happens in install.sh / install.py.
#
#  If macOS says the file "cannot be opened because it is from an
#  unidentified developer", right-click it and choose Open once, or run:
#      xattr -d com.apple.quarantine install.command
# ─────────────────────────────────────────────────────────────────────────────
cd "$(dirname "$0")" || exit 1
exec bash ./install.sh "$@"
