#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  🎬 YouTube AI Agent Studio — installer bootstrap
#  Fork: unknownmatthias/youtube-agentic-ai-studio
#
#  One-liner (fresh machine):
#      curl -fsSL https://raw.githubusercontent.com/unknownmatthias/youtube-agentic-ai-studio/main/install.sh | bash
#
#  Or, inside a clone:
#      ./install.sh
#
#  This script only finds a suitable Python and hands off to install.py,
#  which does the real work (venv, dependencies, API keys, launchers).
#
#  Environment overrides:
#      YT_STUDIO_BRANCH=main      branch to install from
#      YT_STUDIO_DIR=~/yt-studio  where to install
#      PYTHON=/path/to/python3    interpreter to use
#  Anything else is forwarded to install.py (see ./install.sh --help).
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

OWNER="unknownmatthias"
REPO="youtube-agentic-ai-studio"
BRANCH="${YT_STUDIO_BRANCH:-main}"

# ── colours ──────────────────────────────────────────────────────────────────
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
  C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_RED=$'\033[31m'; C_CYAN=$'\033[36m'
else
  C_RESET=""; C_BOLD=""; C_DIM=""; C_GREEN=""; C_YELLOW=""; C_RED=""; C_CYAN=""
fi

say()  { printf '%s\n' "$*"; }
ok()   { printf '  %s✔%s  %s\n'  "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '  %s!%s  %s\n'  "$C_YELLOW" "$C_RESET" "$*"; }
err()  { printf '  %s✘%s  %s\n'  "$C_RED" "$C_RESET" "$*" >&2; }
step() { printf '\n%s%s%s\n' "$C_BOLD" "$*" "$C_RESET"; }

# ── pull --branch out of the arguments so we fetch the right installer ───────
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --branch)      BRANCH="${2:-$BRANCH}"; ARGS+=("$1"); [ $# -gt 1 ] && ARGS+=("$2"); shift 2 || shift $# ;;
    --branch=*)    BRANCH="${1#*=}";       ARGS+=("$1"); shift ;;
    *)             ARGS+=("$1"); shift ;;
  esac
done

INSTALLER_URL="https://raw.githubusercontent.com/${OWNER}/${REPO}/${BRANCH}/install.py"

# ── locate an interpreter (3.10+) ────────────────────────────────────────────
MIN_OK=0
py_ok() { "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; }

PYTHON_BIN="${PYTHON:-}"
if [ -n "$PYTHON_BIN" ] && py_ok "$PYTHON_BIN"; then
  MIN_OK=1
else
  for candidate in \
    /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3.10 \
    /usr/local/bin/python3.13 /usr/local/bin/python3.12 /usr/local/bin/python3.11 /usr/local/bin/python3.10 \
    "$HOME/.pyenv/shims/python3" python3.13 python3.12 python3.11 python3.10 python3 python
  do
    if command -v "$candidate" >/dev/null 2>&1 && py_ok "$candidate"; then
      PYTHON_BIN="$(command -v "$candidate")"
      MIN_OK=1
      break
    fi
  done
fi

if [ "$MIN_OK" -ne 1 ]; then
  warn "Python 3.10 or newer is required and none was found."
  if [ "$(uname -s)" = "Darwin" ] && command -v brew >/dev/null 2>&1; then
    if [ -t 0 ]; then
      read -r -p "  Install Python 3.12 with Homebrew now? [Y/n] " reply
      case "$reply" in n|N) ;; *) brew install python@3.12 ;; esac
    else
      say "  Run:  brew install python@3.12"
      exit 1
    fi
    for candidate in /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12 "$(command -v python3 || true)"; do
      if [ -n "$candidate" ] && py_ok "$candidate"; then PYTHON_BIN="$candidate"; MIN_OK=1; break; fi
    done
  fi
fi

if [ "$MIN_OK" -ne 1 ]; then
  err "Could not find Python 3.10+."
  say  "  Install it from https://www.python.org/downloads/ and re-run this script."
  exit 1
fi
ok "Python $("$PYTHON_BIN" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')  ${C_DIM}${PYTHON_BIN}${C_RESET}"

# ── find install.py: next to this script, else download it ───────────────────
SCRIPT_DIR=""
if [ -n "${BASH_SOURCE[0]:-}" ]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" || SCRIPT_DIR=""
fi

INSTALLER=""
if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/install.py" ]; then
  INSTALLER="$SCRIPT_DIR/install.py"
  step "Using the installer in this checkout"
else
  step "Downloading the installer (${OWNER}/${REPO}@${BRANCH})"
  TMPDIR_INSTALL="$(mktemp -d)"
  cleanup() { rm -rf "$TMPDIR_INSTALL"; }
  trap cleanup EXIT
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$INSTALLER_URL" -o "$TMPDIR_INSTALL/install.py" \
      || { err "Download failed: $INSTALLER_URL"; exit 1; }
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$TMPDIR_INSTALL/install.py" "$INSTALLER_URL" \
      || { err "Download failed: $INSTALLER_URL"; exit 1; }
  else
    err "Need curl or wget to download the installer."
    say  "  Clone the repo instead:  git clone https://github.com/${OWNER}/${REPO}.git"
    exit 1
  fi
  INSTALLER="$TMPDIR_INSTALL/install.py"
  ok "installer downloaded"
fi

# ── hand off (keep prompts working even when piped from curl) ───────────────
if [ -n "${YT_STUDIO_DIR:-}" ]; then
  ARGS+=("--dir" "$YT_STUDIO_DIR")
fi

say ""

# Keep the installer's prompts working even when this script was piped from curl.
# Reconnect stdin to the user's terminal when there is one (tested in a subshell
# so a missing controlling terminal can't kill us); otherwise run non-interactively.
if [ -t 0 ]; then
  exec "$PYTHON_BIN" "$INSTALLER" "${ARGS[@]}"
elif ( exec < /dev/tty ) 2>/dev/null; then
  "$PYTHON_BIN" "$INSTALLER" "${ARGS[@]}" < /dev/tty
  exit $?
else
  exec "$PYTHON_BIN" "$INSTALLER" "${ARGS[@]}"
fi
