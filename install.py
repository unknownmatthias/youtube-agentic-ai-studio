#!/usr/bin/env python3
"""
install.py — one-shot installer for the unknownmatthias fork of
              🎬 YouTube AI Agent Studio

Run it any of these ways:

    # inside an existing clone
    python3 install.py

    # fresh machine — clone the fork, then install into ./youtube-agentic-ai-studio
    python3 install.py --dir youtube-agentic-ai-studio

    # non-interactive (CI / scripted) — keys come from the environment
    GEMINI_API_KEY=... PEXELS_API_KEY=... python3 install.py --yes

    # check an existing install
    python3 install.py --doctor

It is deliberately stdlib-only so it can run on a bare Python before any
dependencies exist. Everything it creates is listed in .gitignore.

Steps
  1. preflight      Python 3.10+, git, ffmpeg
  2. source         clone the fork (or reuse/download a checkout)
  3. venv           create an isolated virtualenv
  4. dependencies   pip install -r requirements.txt
  5. ffmpeg         detect, or offer to install it
  6. configure      write .env with your API keys (masked prompts)
  7. verify         import every dependency, resolve ffmpeg, check keys
"""

from __future__ import annotations

import argparse
import getpass
import itertools
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
#  CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

APP_NAME       = "YouTube AI Agent Studio"
REPO_OWNER     = "unknownmatthias"
REPO_NAME      = "youtube-agentic-ai-studio"
REPO_URL       = f"https://github.com/{REPO_OWNER}/{REPO_NAME}.git"
DEFAULT_BRANCH = "main"
MIN_PYTHON     = (3, 10)
GUI_PORT       = 7070
STATE_FILE     = ".install-state.json"
VENV_DIRNAME   = ".venv"
REQUIRED_DIRS  = ("output", "output/images", "music library")
INSTALL_LOG    = "install.log"

# key, human name, required, where to get it
KEY_SPECS = (
    ("GEMINI_API_KEY",     "Google Gemini  (AI research + scripts)", True,
     "https://aistudio.google.com/apikey"),
    ("PEXELS_API_KEY",     "Pexels         (free stock images)",     True,
     "https://www.pexels.com/api/"),
    ("ELEVENLABS_API_KEY", "ElevenLabs     (optional)",              False,
     "https://elevenlabs.io/app/settings/api-keys"),
)
PLACEHOLDERS = {
    "", "YOUR_GEMINI_API_KEY", "YOUR_PEXELS_API_KEY", "YOUR_ELEVENLABS_KEY",
    "your_gemini_api_key_here", "your_pexels_api_key_here", "your_elevenlabs_key_here",
}

IS_MAC   = sys.platform == "darwin"
IS_WIN   = os.name == "nt"
IS_LINUX = sys.platform.startswith("linux")


# ─────────────────────────────────────────────────────────────────────────────
#  STDOUT ENCODING
#
#  Windows consoles often default to cp1252, which cannot encode 🎬 / ✔ / ─ —
#  printing one raises UnicodeEncodeError and kills the installer before its
#  first real line of output. Force UTF-8, and fall back to plain ASCII glyphs
#  when the console itself cannot display them.
# ─────────────────────────────────────────────────────────────────────────────

def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:      # not a TextIOWrapper (captured, redirected, …)
            pass


def _console_speaks_utf8() -> bool:
    if not IS_WIN:
        return True
    try:
        import ctypes
        return ctypes.windll.kernel32.GetConsoleOutputCP() == 65001
    except Exception:
        return True


def _can_encode(text: str) -> bool:
    enc = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        text.encode(enc)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


_configure_stdio()
_UNICODE_OK = _console_speaks_utf8() and _can_encode("🎬─✔✘═•→")


def _g(emoji: str, fallback: str = "") -> str:
    """Return `emoji`, or an ASCII `fallback` the console cannot display it."""
    return emoji if _UNICODE_OK else fallback

# ─────────────────────────────────────────────────────────────────────────────
#  OUTPUT HELPERS
# ─────────────────────────────────────────────────────────────────────────────

_COLOR = (
    sys.stdout.isatty()
    and os.environ.get("NO_COLOR") is None
    and (not IS_WIN or os.environ.get("TERM") or os.environ.get("WT_SESSION"))
)
if IS_WIN and _COLOR:  # enable ANSI escapes on Windows 10+
    os.system("")


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def bold(t):   return _c(t, "1")
def dim(t):    return _c(t, "2")
def green(t):  return _c(t, "32")
def yellow(t): return _c(t, "33")
def red(t):    return _c(t, "31")
def cyan(t):   return _c(t, "36")


_LOG_PATH = None
_VERBOSE = False


def log(msg: str) -> None:
    """Append a line to the install log (never to stdout)."""
    if not _LOG_PATH:
        return
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(msg.rstrip() + "\n")
    except OSError:
        pass


def info(msg: str = "") -> None:
    print(msg)
    log(msg)


def ok(msg: str) -> None:
    print(f"  {_g(green('✔'), green('+'))}  {msg}")
    log(f"OK   {msg}")


def warn(msg: str) -> None:
    print(f"  {yellow('!')}  {yellow(msg)}")
    log(f"WARN {msg}")


def fail(msg: str) -> None:
    print(f"  {_g(red('✘'), red('x'))}  {red(msg)}")
    log(f"FAIL {msg}")


def heading(msg: str) -> None:
    print(f"\n{bold(msg)}")


def rule(char: str = None, width: int = 68) -> None:
    char = char or _g("─", "-")
    print(dim(char * width))


_spinner = None


def _spin(label: str) -> None:
    global _spinner
    if not sys.stdout.isatty():
        return
    frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏" if _UNICODE_OK else "|/-\\"
    if _spinner is None:
        _spinner = itertools.cycle(frames)
    frame = next(_spinner)
    sys.stdout.write(f"\r  {cyan(frame)}  {label}   ")
    sys.stdout.flush()


def _spin_stop(label: str = "") -> None:
    if sys.stdout.isatty():
        sys.stdout.write("\r" + " " * (len(label) + 12) + "\r")
        sys.stdout.flush()


def _supports_unicode() -> bool:
    enc = (getattr(sys.stdout, "encoding", "") or "").lower()
    return "utf" in enc


# ─────────────────────────────────────────────────────────────────────────────
#  PROMPTING  (auto-skips when not attached to a terminal)
# ─────────────────────────────────────────────────────────────────────────────

class Session:
    """Holds CLI options that every step needs."""

    def __init__(self, args):
        self.args = args
        self.interactive = (
            sys.stdin.isatty() and sys.stdout.isatty() and not args.yes
        )

    def ask(self, question: str, default: bool = True) -> bool:
        if not self.interactive:
            auto = "yes" if default else "no"
            print(f"  {dim('?')}  {question}  {dim('[auto: ' + auto + ']')}")
            return default
        suffix = "Y/n" if default else "y/N"
        while True:
            try:
                ans = input(f"  {cyan('?')}  {question} [{suffix}] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                return default
            if not ans:
                return default
            if ans in ("y", "yes"):
                return True
            if ans in ("n", "no"):
                return False
            print("      Please answer y or n.")


# ─────────────────────────────────────────────────────────────────────────────
#  SHELL / PROCESS HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def which(program: str):
    return shutil.which(program)


def run(argv, cwd=None, env=None, label=None, show=False, timeout=1800,
        check=False):
    """
    Run a command. Output is captured for the log; while it runs we show a
    spinner (or the raw output when show=True).

    Returns (returncode, combined_output).
    """
    printable = " ".join(str(a) for a in argv)
    log(f"$ {printable}   (cwd={cwd})")
    cmd = [str(a) for a in argv]
    try:
        if show or _VERBOSE:
            proc = subprocess.run(cmd, cwd=cwd, env=env, timeout=timeout, check=False)
            return proc.returncode, ""
        with tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as buf:
            proc = subprocess.Popen(
                cmd, cwd=cwd, env=env, stdout=buf, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, text=True,
            )
            label = label or "working…"
            while proc.poll() is None:
                _spin(label)
                time.sleep(0.12)
            _spin_stop(label)
            buf.seek(0)
            out = buf.read()
    except FileNotFoundError as exc:
        log(f"ERROR FileNotFoundError: {exc}")
        if check:
            raise
        return 127, str(exc)
    except subprocess.TimeoutExpired:
        log("ERROR timeout")
        return 124, "timed out"
    log(out)
    return proc.returncode, out


def tail(text: str, lines: int = 18) -> str:
    parts = [ln for ln in (text or "").splitlines() if ln.strip()]
    keep = parts[-lines:]
    return "\n".join(f"      {dim(ln)}" for ln in keep)


def _clean_env() -> dict:
    env = os.environ.copy()
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    env.setdefault("PYTHONUNBUFFERED", "1")
    # never leak a foreign venv into our subprocesses
    env.pop("VIRTUAL_ENV", None)
    env.pop("PYTHONHOME", None)
    if env.get("PATH"):
        env["PATH"] = os.pathsep.join(
            p for p in env["PATH"].split(os.pathsep)
            if "youtube-agentic-ai-studio" not in p and p not in ("", ".")
        )
    return env


# ─────────────────────────────────────────────────────────────────────────────
#  STEP 1 — PREFLIGHT
# ─────────────────────────────────────────────────────────────────────────────

def platform_summary() -> str:
    bits = platform.machine() or "?"
    if IS_MAC:
        return f"macOS {platform.mac_ver()[0] or '?'} ({bits})"
    if IS_WIN:
        return f"Windows {platform.release()} ({bits})"
    return f"{platform.system()} {platform.release()} ({bits})"


def python_version(argv):
    """Return (major, minor, micro) for an interpreter, or None."""
    try:
        out = subprocess.run(
            [str(a) for a in argv] + ["-c", "import sys; print('%d.%d.%d' % sys.version_info[:3])"],
            capture_output=True, text=True, timeout=60, env=_clean_env(),
        )
        if out.returncode == 0:
            return tuple(int(x) for x in out.stdout.strip().split("."))
    except Exception:
        pass
    return None


def python_candidates(explicit=None):
    """Yield candidate interpreter argv prefixes, best-guess order."""
    seen = set()

    def add(argv):
        key = tuple(argv)
        if key not in seen:
            seen.add(key)
            return argv
        return None

    if explicit:
        cand = add([explicit])
        if cand:
            yield cand

    env_py = os.environ.get("PYTHON")
    if env_py:
        cand = add([env_py])
        if cand:
            yield cand

    # Homebrew / pyenv / macports installs (macOS ships 3.9, which is too old)
    bases = ["/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin",
             os.path.expanduser("~/.pyenv/shims"), os.path.expanduser("~/homebrew/bin")]
    for base in bases:
        for minor in range(13, 9, -1):
            cand = add([f"{base}/python3.{minor}"])
            if cand:
                yield cand

    # Windows py launcher
    if IS_WIN and which("py"):
        for minor in range(13, 9, -1):
            cand = add(["py", f"-3.{minor}"])
            if cand:
                yield cand
        cand = add(["py", "-3"])
        if cand:
            yield cand

    for name in ("python3.13", "python3.12", "python3.11", "python3.10",
                 "python3", "python"):
        found = which(name)
        if found:
            cand = add([found])
            if cand:
                yield cand

    for fallback in ("/usr/bin/python3", "/usr/bin/python"):
        cand = add([fallback])
        if cand:
            yield cand


def brew_prefix() -> str:
    for prefix in ("/opt/homebrew", "/usr/local", os.path.expanduser("~/homebrew")):
        if os.path.exists(f"{prefix}/bin/brew"):
            return prefix
    found = which("brew")
    if found:
        return str(Path(found).resolve().parent.parent)
    return "/usr/local"


def package_commands(program: str):
    """
    Candidate system-package commands to install `program` on this OS.
    Returns [(human label, argv, needs_root)].
    """
    if IS_MAC:
        return [
            (f"brew install {program}", ["brew", "install", program], False),
            (f"sudo port install {program}", ["sudo", "port", "install", program], True),
        ]
    if IS_WIN:
        ids = {"ffmpeg": "Gyan.FFmpeg", "git": "Git.Git"}
        return [
            (f"winget install {ids.get(program, program)}",
             ["winget", "install", "-e", "--id", ids.get(program, program),
              "--accept-source-agreements", "--accept-package-agreements"], False),
            (f"choco install {program}", ["choco", "install", "-y", program], False),
            (f"scoop install {program}", ["scoop", "install", program], False),
        ]
    if which("apt-get"):
        return [(f"sudo apt-get install -y {program}", ["sudo", "apt-get", "install", "-y", program], True)]
    if which("dnf"):
        return [(f"sudo dnf install -y {program}", ["sudo", "dnf", "install", "-y", program], True)]
    if which("yum"):
        return [(f"sudo yum install -y {program}", ["sudo", "yum", "install", "-y", program], True)]
    if which("pacman"):
        return [(f"sudo pacman -S --noconfirm {program}", ["sudo", "pacman", "-S", "--noconfirm", program], True)]
    if which("zypper"):
        return [(f"sudo zypper install -y {program}", ["sudo", "zypper", "install", "-y", program], True)]
    if which("apk"):
        return [(f"apk add {program}", ["apk", "add", program], True)]
    return []


def _first_available_pkg_cmd(program: str):
    for label, argv, needs_root in package_commands(program):
        tool = argv[0]
        if tool == "sudo":
            if not which("sudo"):
                continue
            tool = argv[1]
        if which(tool) or os.path.exists(f"/opt/homebrew/bin/{tool}") \
                or os.path.exists(f"/usr/local/bin/{tool}"):
            return label, argv, needs_root
    return None


def ensure_tool(sess, program: str, nice_name: str, required: bool,
                offer: bool = True, skip_hint: str = "") -> bool:
    """
    Make sure `program` is on PATH, offering to install it when missing.

    required=True  → the caller cannot proceed without it
    offer=False    → only detect, never install (used by --no-system-deps)
    Returns True when the tool is present afterwards.
    """
    if which(program):
        path = which(program)
        version = ""
        rc, out = run([program, "-version"], label=f"checking {nice_name}", timeout=60)
        if rc == 0 and out.strip():
            version = "  " + dim(out.strip().splitlines()[0][:60])
        ok(f"{nice_name} found {dim(path)}{version}")
        return True

    warn(f"{nice_name} not found" + ("." if required else " — recommended, but optional."))
    if skip_hint:
        info(f"      {dim(skip_hint)}")
    if not offer:
        return False

    found = _first_available_pkg_cmd(program)
    if not found:
        if IS_MAC:
            info(f"      Install it with Homebrew:  brew install {program}")
            if program == "ffmpeg":
                info("      (no Homebrew? https://brew.sh — or grab a macOS build from "
                     "https://evermeet.cx/ffmpeg/ )")
        else:
            info(f"      Install {program} with your package manager, then re-run this installer.")
        return False

    label, argv, needs_root = found
    if needs_root and hasattr(os, "geteuid") and os.geteuid() == 0:
        argv = [a for a in argv if a != "sudo"]
    if not sess.ask(f"Install it now?  ({label})", default=True):
        info(f"      Skipped — install {nice_name} manually later.")
        return False

    info(f"      Running: {bold(label)}")
    rc, out = run(argv, label=f"installing {nice_name}", timeout=1800)
    if rc != 0:
        fail(f"Could not install {nice_name} automatically (exit {rc}).")
        print(tail(out))
        info(f"      Install it manually:  {label}")
        return False
    if which(program):
        ok(f"{nice_name} installed {dim(which(program))}")
        return True
    # Homebrew/python may need a PATH refresh in this shell
    for extra in (f"{brew_prefix()}/bin", "/opt/homebrew/bin", "/usr/local/bin"):
        if os.path.exists(f"{extra}/{program}"):
            os.environ["PATH"] = extra + os.pathsep + os.environ.get("PATH", "")
            ok(f"{nice_name} installed {dim(extra + '/' + program)}")
            return True
    warn(f"{nice_name} install finished but it is still not on PATH — you may need to restart your shell.")
    return False


def ensure_python(sess, explicit=None):
    """Find an interpreter >= MIN_PYTHON, offering to install one if missing."""
    for argv in python_candidates(explicit):
        ver = python_version(argv)
        if ver and ver[:2] >= MIN_PYTHON:
            ok(f"Python {'.'.join(str(v) for v in ver)}  {dim(argv[0])}")
            return list(argv)
    # remember why we failed
    too_old = []
    for argv in python_candidates(explicit):
        ver = python_version(argv)
        if ver:
            too_old.append((argv[0], ".".join(str(v) for v in ver)))

    if too_old:
        warn(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required. Found:")
        for path, ver in too_old[:5]:
            info(f"      {ver}  {dim(path)}  (too old)")
    else:
        warn(f"No Python interpreter found. Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required.")

    if IS_MAC:
        brew = f"{brew_prefix()}/bin/brew"
        label, argv = ("brew install python@3.12", [brew, "install", "python@3.12"])
        if which("brew") or os.path.exists(brew):
            if sess.ask(f"Install a modern Python now?  ({label})", default=True):
                rc, out = run(argv, label="installing Python 3.12", timeout=1800)
                if rc == 0:
                    os.environ["PATH"] = f"{brew_prefix()}/bin" + os.pathsep + os.environ.get("PATH", "")
                    for cand in python_candidates(explicit):
                        ver = python_version(cand)
                        if ver and ver[:2] >= MIN_PYTHON:
                            ok(f"Python {'.'.join(str(v) for v in ver)}  {dim(cand[0])}")
                            return list(cand)
                fail("Homebrew could not install Python.")
                print(tail(out))
        info("      Or download the installer from https://www.python.org/downloads/")
    elif IS_WIN:
        info("      Install Python 3.11+ from https://www.python.org/downloads/ "
             "(tick \"Add python.exe to PATH\") and re-run this installer.")
    else:
        info("      Install it with your package manager, e.g.  sudo apt install python3.11 python3.11-venv")
    return None


# ─────────────────────────────────────────────────────────────────────────────
#  STEP 2 — GET THE SOURCE
# ─────────────────────────────────────────────────────────────────────────────

REPO_MARKERS = ("config.py", "gui.py", "requirements.txt", "agents")


def looks_like_repo(path: Path) -> bool:
    return path.is_dir() and all((path / m).exists() for m in REPO_MARKERS)


def git_version(sess, offer=True):
    if which("git"):
        return True
    return ensure_tool(sess, "git", "Git", required=False, offer=offer,
                       skip_hint="Without it we download a source snapshot instead "
                                 "(git pull / --upgrade won't be available).")


def _git(cwd, *args, timeout=600):
    return run(["git", *args], cwd=cwd, label=f"git {' '.join(args)}", timeout=timeout)


def git_is_dirty(cwd: Path) -> bool:
    rc, out = run(["git", "status", "--porcelain"], cwd=str(cwd), timeout=120)
    return rc == 0 and bool(out.strip())


def current_commit(cwd: Path):
    rc, out = run(["git", "rev-parse", "--short", "HEAD"], cwd=str(cwd), timeout=120)
    return out.strip() if rc == 0 else None


def current_branch(cwd: Path):
    rc, out = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(cwd), timeout=120)
    return out.strip() if rc == 0 else None


def download_snapshot(dest: Path, branch: str) -> bool:
    """Clone-free fallback: fetch a GitHub tarball/zip and unpack it."""
    urls = [
        (f"https://codeload.github.com/{REPO_OWNER}/{REPO_NAME}/tar.gz/refs/heads/{branch}", "tar"),
        (f"https://github.com/{REPO_OWNER}/{REPO_NAME}/archive/refs/heads/{branch}.tar.gz", "tar"),
        (f"https://github.com/{REPO_OWNER}/{REPO_NAME}/archive/refs/heads/{branch}.zip", "zip"),
    ]
    tmpdir = Path(tempfile.mkdtemp(prefix="yt-studio-dl-"))
    for url, kind in urls:
        try:
            info(f"      Downloading {url}")
            with urllib.request.urlopen(url, timeout=120) as resp:
                blob = resp.read()
            archive = tmpdir / f"src.{ 'tar.gz' if kind == 'tar' else 'zip' }"
            archive.write_bytes(blob)
            if kind == "tar":
                with tarfile.open(archive) as tf:
                    tf.extractall(tmpdir)
            else:
                with zipfile.ZipFile(archive) as zf:
                    zf.extractall(tmpdir)
            inner = next((p for p in tmpdir.iterdir()
                          if p.is_dir() and p.name != "__MACOSX"), None)
            if inner and looks_like_repo(inner):
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.move(str(inner), str(dest))
                shutil.rmtree(tmpdir, ignore_errors=True)
                return True
        except Exception as exc:  # network / parse errors — try the next URL
            log(f"download failed {url}: {exc}")
            continue
    shutil.rmtree(tmpdir, ignore_errors=True)
    return False


def acquire_source(sess, install_dir: Path, repo: str, branch: str, local_source):
    """Make sure install_dir contains the project. Returns (ok, fresh_clone)."""
    install_dir = install_dir.expanduser().resolve()

    # A) reuse this checkout
    if looks_like_repo(install_dir):
        ok(f"Using existing checkout  {dim(str(install_dir))}")
        if (install_dir / ".git").is_dir() and which("git"):
            br = current_branch(install_dir)
            commit = current_commit(install_dir)
            if commit:
                info(f"      branch {bold(br or '?')} @ {commit}")
            if sess.args.upgrade or sess.ask("Update it with git pull?", default=False):
                if git_is_dirty(install_dir):
                    warn("Working tree has local changes — skipping git pull.")
                else:
                    rc, out = run(["git", "pull", "--ff-only"], cwd=str(install_dir),
                                  label="git pull", timeout=600)
                    if rc == 0:
                        ok("Updated to latest commit")
                    else:
                        warn("git pull failed (you may be on a local branch). Continuing.")
                        print(tail(out, 6))
        return True, False

    # B) copy from a local checkout (offline installs / testing)
    if local_source:
        src = Path(local_source).expanduser().resolve()
        if looks_like_repo(src):
            install_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(
                src, install_dir,
                ignore=shutil.ignore_patterns(
                    ".git", VENV_DIRNAME, "__pycache__", "output", "*.log",
                    ".install-state.json", ".env", "node_modules",
                ),
            )
            ok(f"Copied source from  {dim(str(src))}")
            return True, True
        fail(f"--source {src} does not look like a {APP_NAME} checkout.")
        return False, False

    if install_dir.exists() and any(install_dir.iterdir()):
        fail(f"{install_dir} exists and is not empty — refusing to clone over it.")
        info("      Re-run with --dir <path> or run this installer from inside your clone.")
        return False, False

    # C) clone
    if which("git"):
        install_dir.parent.mkdir(parents=True, exist_ok=True)
        info(f"      Cloning {bold(repo)} ({branch}) …")
        rc, out = run(["git", "clone", "--depth", "1", "--branch", branch, repo,
                       str(install_dir)], label="cloning", timeout=900)
        if rc == 0:
            ok(f"Cloned into  {dim(str(install_dir))}")
            return True, True
        fail(f"git clone failed (exit {rc}).")
        print(tail(out))
        # depth-1 clone can fail on a non-default branch with old git — retry full clone
        info("      Retrying without --depth …")
        shutil.rmtree(install_dir, ignore_errors=True)
        rc, out = run(["git", "clone", "--branch", branch, repo, str(install_dir)],
                      label="cloning", timeout=1200)
        if rc == 0:
            ok(f"Cloned into  {dim(str(install_dir))}")
            return True, True
        print(tail(out))

    # D) no git → download a snapshot
    if not which("git") or not looks_like_repo(install_dir):
        warn("Falling back to downloading a source snapshot (git not available).")
        if download_snapshot(install_dir, branch):
            ok(f"Downloaded source into  {dim(str(install_dir))}")
            return True, True

    fail("Could not obtain the source code.")
    return False, False


# ─────────────────────────────────────────────────────────────────────────────
#  STEP 3 — VIRTUAL ENVIRONMENT + DEPENDENCIES
# ─────────────────────────────────────────────────────────────────────────────

def venv_python_path(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if IS_WIN else "bin/python")


def create_venv(sess, py, venv: Path) -> bool:
    if venv_python_path(venv).exists():
        ver = python_version([venv_python_path(venv)])
        if ver and ver[:2] >= MIN_PYTHON:
            ok(f"Reusing virtualenv  {dim(str(venv))}")
            return True
        warn("Existing virtualenv is too old — recreating it.")
        shutil.rmtree(venv, ignore_errors=True)

    venv.parent.mkdir(parents=True, exist_ok=True)
    info(f"      Creating virtualenv in {dim(str(venv))}")
    rc, out = run([*py, "-m", "venv", str(venv)], label="creating virtualenv", timeout=600)
    if rc == 0 and venv_python_path(venv).exists():
        ok("Virtualenv created")
        return True

    # Debian/Ubuntu: python3-venv is a separate package
    fail(f"Could not create a virtualenv (exit {rc}).")
    print(tail(out))
    if IS_LINUX:
        info("      On Debian/Ubuntu install it with:  sudo apt install python3-venv")
        if sess.ask("Try that now?", default=True):
            rc2, out2 = run(["sudo", "apt-get", "install", "-y", "python3-venv"],
                            label="installing python3-venv", timeout=900)
            if rc2 == 0:
                rc, out = run([*py, "-m", "venv", str(venv)], label="creating virtualenv",
                              timeout=600)
                if rc == 0 and venv_python_path(venv).exists():
                    ok("Virtualenv created")
                    return True
                print(tail(out))
            else:
                print(tail(out2))
    return False


def pip_install(sess, venv: Path, requirements: Path, upgrade: bool) -> bool:
    py = str(venv_python_path(venv))
    env = _clean_env()

    rc, out = run([py, "-m", "pip", "install", "--upgrade", "pip", "wheel", "setuptools"],
                  cwd=str(requirements.parent), env=env,
                  label="upgrading pip", timeout=900)
    if rc != 0:
        warn("pip upgrade failed — continuing with the bundled pip.")
        print(tail(out, 8))

    cmd = [py, "-m", "pip", "install", "-r", str(requirements)]
    if upgrade:
        cmd.append("--upgrade")
    info("      This downloads ~250 MB the first time (moviepy, pillow, google-genai…).")
    rc, out = run(cmd, cwd=str(requirements.parent), env=env,
                  label="installing dependencies", timeout=2400)
    if rc != 0:
        fail("pip install failed.")
        print(tail(out, 30))
        info(f"      Full log: {_LOG_PATH}")
        return False
    ok("Dependencies installed")
    return True


# ─────────────────────────────────────────────────────────────────────────────
#  STEP 4 — API KEYS (.env)
# ─────────────────────────────────────────────────────────────────────────────

def read_env(path: Path) -> dict:
    env = {}
    if not path.exists():
        return env
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    except OSError as exc:
        log(f"read_env failed: {exc}")
    return env


def is_placeholder(value) -> bool:
    return (value or "").strip() in PLACEHOLDERS or str(value).startswith("YOUR_")


def masked(value: str) -> str:
    v = (value or "").strip()
    if len(v) <= 10:
        return v[:3] + "…" if v else "(empty)"
    return f"{v[:6]}…{v[-4:]}"


def write_env(path: Path, values: dict) -> None:
    lines = [
        "# YouTube AI Agent Studio — environment",
        "# Generated by install.py — do NOT commit this file.",
        "# Precedence: config.py literal > real env var > this file.",
        "",
    ]
    for key, _name, _req, _url in KEY_SPECS:
        lines.append(f"{key}={values.get(key, '')}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    try:
        if not IS_WIN:
            os.chmod(path, 0o600)
    except OSError:
        pass


def prompt_for_key(sess, key, name, required, url, existing):
    """Return the value to store for `key` (or None to keep the current one)."""
    prefill = os.environ.get(key, "")
    if prefill and not is_placeholder(prefill):
        ok(f"{name}: using {masked(prefill)} from your environment")
        return prefill

    if not sess.interactive:
        if required:
            warn(f"{name}: not set (non-interactive). "
                 f"Set it later in .env or in config.py.")
        return "" if required else (existing if not is_placeholder(existing) else "")

    print(f"\n  {bold(name)}")
    print(f"  {dim('Get a free key:')} {cyan(url)}")
    hint = ""
    if existing and not is_placeholder(existing):
        hint = f"  (leave blank to keep {masked(existing)})"
    try:
        raw = getpass.getpass(f"  Paste your key{hint}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None if (existing and not is_placeholder(existing)) else ""
    if raw:
        return raw
    if existing and not is_placeholder(existing):
        return None          # keep
    if required:
        warn("Skipped — you can add it later in .env or via Settings in the GUI.")
    return ""


def configure_env(sess, install_dir: Path) -> bool:
    env_path = install_dir / ".env"
    example = install_dir / ".env.example"
    existing = read_env(env_path) if env_path.exists() else {}

    if env_path.exists() and not sess.args.reconfigure:
        missing = [k for k, _n, req, _u in KEY_SPECS
                   if req and is_placeholder(existing.get(k))]
        if not missing:
            ok(f".env already configured  {dim(str(env_path))}")
            return True
        warn(f".env exists but {', '.join(missing)} look like placeholders.")
        if not sess.ask("Enter your API keys now?", default=True):
            return True
    elif not example.exists():
        warn(".env.example is missing — creating .env from scratch.")

    info(f"\n  {bold('API keys')}  {dim('(free tiers are enough — hidden as you type)')}")

    values = dict(existing)
    for key, name, required, url in KEY_SPECS:
        current = values.get(key, "")
        # don't re-prompt for optional keys that are already set
        if not required and not is_placeholder(current) and not sess.args.reconfigure:
            continue
        got = prompt_for_key(sess, key, name, required, url, current)
        if got is not None:
            values[key] = got

    write_env(env_path, values)
    ok(f"Wrote {dim(str(env_path))}  (permissions 600)")
    return True


# ─────────────────────────────────────────────────────────────────────────────
#  STEP 5 — SCAFFOLD + LAUNCHERS
# ─────────────────────────────────────────────────────────────────────────────

def scaffold(install_dir: Path) -> None:
    for rel in REQUIRED_DIRS:
        path = install_dir / rel
        path.mkdir(parents=True, exist_ok=True)
        keep = path / ".gitkeep"
        if rel != "output/images":
            try:
                keep.touch(exist_ok=True)
            except OSError:
                pass
    ok("Created output/, output/images/ and music library/")


LAUNCHER_SH = """\
#!/bin/bash
# {app} — {label}
# Generated by install.py — safe to edit or delete.
cd "$(dirname "$0")" || exit 1

PY="{python}"
if [ ! -x "$PY" ]; then
  echo "  ✘  Virtual environment not found at {venv}"
  echo "     Re-run the installer:  python3 install.py"
  exit 1
fi

echo "  🎬  {app}"
echo "     {url}"
echo "     Press Ctrl+C in this window to stop it."
echo
exec "$PY" {script}
"""

LAUNCHER_COMMAND = """\
#!/bin/bash
# {app} — {label}
# Generated by install.py. Double-click this file to run.
cd "$(dirname "$0")" || exit 1

PY="{python}"
if [ ! -x "$PY" ]; then
  echo "  ✘  Virtual environment not found at {venv}"
  echo "     Re-run the installer:  python3 install.py"
  read -n 1 -s -r -p "     Press any key to close…"
  echo
  exit 1
fi

echo "  🎬  {app}"
echo "     {url}"
echo "     Press Ctrl+C in this window to stop it."
echo
"$PY" {script}
STATUS=$?
echo
if [ $STATUS -ne 0 ]; then
  echo "  ✘  Exited with status $STATUS — see the message above."
else
  echo "  ✔  Stopped."
fi
read -n 1 -s -r -p "  Press any key to close…"
echo
"""

LAUNCHER_BAT = """\
@echo off
REM {app} — {label}
REM Generated by install.py — safe to edit or delete.
cd /d "%~dp0"

set PY={python}
if not exist "%PY%" (
  echo   X  Virtual environment not found at {venv}
  echo      Re-run the installer:  python install.py
  pause
  exit /b 1
)

echo   {app}
echo      {url}
echo      Press Ctrl+C in this window to stop it.
echo.
"%PY%" {script}
pause
"""


def write_launcher(install_dir: Path, script: str, label: str, url: str, stem: str) -> list:
    py_rel = ".venv/Scripts/python.exe" if IS_WIN else ".venv/bin/python"
    ctx = dict(app=APP_NAME, label=label, python=py_rel, venv=VENV_DIRNAME,
               script=script, url=url)
    written = []
    if IS_WIN:
        specs = [(f"{stem}.bat", LAUNCHER_BAT, False)]
    elif IS_MAC:
        specs = [(f"{stem}.command", LAUNCHER_COMMAND, True),
                 (f"{stem}.sh", LAUNCHER_SH, True)]
    else:
        specs = [(f"{stem}.sh", LAUNCHER_SH, True)]

    for name, template, executable in specs:
        path = install_dir / name
        path.write_text(template.format(**ctx), encoding="utf-8")
        if executable:
            path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        written.append(name)
    return written


def make_launchers(install_dir: Path) -> list:
    gui_url = f"http://localhost:{GUI_PORT}"
    names = []
    names += write_launcher(install_dir, "gui.py", "GUI dashboard", gui_url, "start-gui")
    names += write_launcher(install_dir, "pipeline.py", "CLI pipeline",
                            "runs in this terminal — review dashboard opens when done",
                            "start-pipeline")
    ok("Created launchers: " + ", ".join(bold(n) for n in names))
    return names


def save_state(install_dir: Path, venv: Path, py, repo: str, branch: str) -> None:
    state = {
        "app": APP_NAME,
        "installer_version": 1,
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "install_dir": str(install_dir),
        "venv": str(venv),
        "python": " ".join(str(p) for p in py),
        "repo": repo,
        "branch": branch,
        "commit": current_commit(install_dir),
        "platform": platform_summary(),
        "gui_url": f"http://localhost:{GUI_PORT}",
    }
    try:
        (install_dir / STATE_FILE).write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError as exc:
        log(f"save_state failed: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
#  STEP 6 — VERIFY / DOCTOR
# ─────────────────────────────────────────────────────────────────────────────

VERIFY_SNIPPET = r'''
import importlib, json, os, shutil, socket, sys

# distribution name -> importable module (they differ for a few packages)
PKG = {
    "moviepy": "moviepy",
    "numpy": "numpy",
    "Pillow": "PIL",
    "flask": "flask",
    "edge-tts": "edge_tts",
    "requests": "requests",
    "google-genai": "google.genai",
    "google-api-python-client": "googleapiclient",
    "google-auth-oauthlib": "google_auth_oauthlib",
    "imageio-ffmpeg": "imageio_ffmpeg",
}
res = {"python": "%d.%d.%d" % sys.version_info[:3], "packages": {},
       "missing": [], "errors": [], "keys": {}, "ffmpeg_binary": None,
       "ffmpeg_system": shutil.which("ffmpeg"), "config_ok": False,
       "dirs": {}, "port_in_use": None}

try:
    from importlib.metadata import version as dist_version
except Exception:                                    # Python < 3.8
    dist_version = None

for dist, module in PKG.items():
    found = None
    if dist_version is not None:
        try:
            found = dist_version(dist)
        except Exception:
            found = None
    if not found:
        try:
            found = getattr(importlib.import_module(module), "__version__", None)
        except Exception:
            found = None
    res["packages"][dist] = found
    if not found:
        res["missing"].append(dist)

try:
    import moviepy.config as _mcfg
    res["ffmpeg_binary"] = _mcfg.FFMPEG_BINARY
except Exception as exc:
    res["errors"].append(f"moviepy: {exc}")

try:
    sys.path.insert(0, os.getcwd())
    import config
    res["config_ok"] = True
    for k in ("GEMINI_API_KEY", "PEXELS_API_KEY", "ELEVENLABS_API_KEY"):
        v = getattr(config, k, "")
        res["keys"][k] = "missing" if (not v or str(v).startswith("YOUR_")) else "set"
except Exception as exc:
    res["errors"].append(f"config: {exc}")

for d in ["output", "output/images", "music library"]:
    res["dirs"][d] = os.path.isdir(d)

try:
    s = socket.socket()
    s.settimeout(0.6)
    res["port_in_use"] = (s.connect_ex(("127.0.0.1", 7070)) == 0)
    s.close()
except Exception:
    res["port_in_use"] = None

print("@@JSON@@" + json.dumps(res))
'''


def run_verify(venv: Path, install_dir: Path, attempts: int = 2):
    """
    Run the dependency/health check inside the virtualenv.

    Retried once on failure: Windows runners (and antivirus scanners
    elsewhere) occasionally produce a transient I/O error while the child
    writes its report, which used to make `--doctor` fail for no reason.
    """
    py = str(venv_python_path(venv))
    out = ""
    for attempt in range(max(1, attempts)):
        rc, out = run([py, "-c", VERIFY_SNIPPET], cwd=str(install_dir),
                      label="verifying install", timeout=300)
        if rc == 0:
            for line in out.splitlines():
                if line.startswith("@@JSON@@"):
                    try:
                        return json.loads(line[len("@@JSON@@"):]), out
                    except json.JSONDecodeError:
                        break
        if attempt + 1 < attempts:
            log(f"verification attempt {attempt + 1} failed, retrying")
            time.sleep(1.5)
    return None, out


def verify_api_keys(venv: Path, install_dir: Path, values: dict, sess) -> None:
    """Optional live check that the Gemini + Pexels keys actually work."""
    py = str(venv_python_path(venv))
    gemini = (values.get("GEMINI_API_KEY") or "").strip()
    pexels = (values.get("PEXELS_API_KEY") or "").strip()
    if is_placeholder(gemini) and is_placeholder(pexels):
        return
    if not sess.ask("Verify the API keys with a live call? (recommended)", default=True):
        return

    snippet = r'''
import json, sys

out = {}
gemini, pexels = sys.argv[1], sys.argv[2]

NET_HINTS = ("ssl", "connection", "timeout", "timed out", "name or service",
             "max retries", "eof", "proxy", "temporary failure", "network",
             "unreachable", "name resolution")

def classify(exc):
    text = str(exc).lower()
    if any(h in text for h in NET_HINTS):
        return "unreachable: " + str(exc)[:120]
    return "failed: " + str(exc)[:160]

if gemini and not gemini.startswith("YOUR_"):
    try:
        from google import genai
        client = genai.Client(api_key=gemini)
        next(iter(client.models.list(config={"page_size": 1})), None)
        out["gemini"] = "ok"
    except Exception as exc:
        out["gemini"] = classify(exc)

if pexels and not pexels.startswith("YOUR_"):
    try:
        import requests
        r = requests.get("https://api.pexels.com/v1/search?query=space&per_page=1",
                         headers={"Authorization": pexels}, timeout=20)
        out["pexels"] = "ok" if r.status_code == 200 else f"failed: HTTP {r.status_code}"
    except Exception as exc:
        out["pexels"] = classify(exc)

print("@@JSON@@" + json.dumps(out))
'''
    rc, out = run([py, "-c", snippet, gemini, pexels], cwd=str(install_dir),
                  label="checking API keys", timeout=180)
    result = None
    for line in out.splitlines():
        if line.startswith("@@JSON@@"):
            try:
                result = json.loads(line[len("@@JSON@@"):])
            except json.JSONDecodeError:
                pass
    if not result:
        warn("Could not reach the APIs (offline?) — skipping key validation.")
        return
    for service, status in result.items():
        display = service.capitalize()
        if status == "ok":
            ok(f"{display} key works")
        elif status.startswith("unreachable"):
            warn(f"Could not reach {display} — key not validated (offline or blocked proxy?)")
        else:
            warn(f"{display} key {status}")
            info("      Check it, then re-run: python3 install.py --reconfigure")


def print_report(install_dir: Path, venv: Path, report: dict, sess) -> bool:
    heading("7 / 7  ·  Verifying the installation")
    if not report:
        fail("Verification could not run.")
        return False

    info(f"      Python {report['python']}  ·  venv {dim(str(venv))}")

    missing = report.get("missing") or []
    if missing:
        for name in missing:
            fail(f"missing package: {name}")
        return False

    core = ("moviepy", "numpy", "Pillow", "flask", "edge-tts", "google-genai", "requests")
    line = "  ".join(f"{k} {dim(v)}" for k, v in report["packages"].items() if k in core)
    ok("All dependencies import cleanly")
    print(f"      {line}")

    if report.get("ffmpeg_system"):
        ok(f"ffmpeg (system)  {dim(report['ffmpeg_system'])}")
    elif report.get("ffmpeg_binary") and os.path.exists(str(report["ffmpeg_binary"])):
        ok("MoviePy will use its bundled ffmpeg "
           f"{dim(str(report['ffmpeg_binary']))}")
        info("      (installing system ffmpeg is optional — rendering already works)")
    else:
        warn("No ffmpeg found — video rendering will fail until you install it.")

    if report.get("config_ok"):
        ok("config.py imports cleanly")
        for key, state in report["keys"].items():
            if key == "ELEVENLABS_API_KEY":
                continue
            if state == "set":
                ok(f"{key} is set")
            else:
                warn(f"{key} is not set — add it in .env or in the GUI's Settings panel")
    else:
        fail("config.py failed to import: " + "; ".join(report.get("errors", [])))

    missing_dirs = [d for d, present in report["dirs"].items() if not present]
    if missing_dirs:
        fail("missing folders: " + ", ".join(missing_dirs))
    else:
        ok("output/, output/images/, music library/ are ready")

    if report.get("port_in_use"):
        warn(f"Port {GUI_PORT} is already in use — the GUI will use the next free port "
             f"or fail to start until you stop the other process.")

    return not missing and report.get("config_ok", False)


# ─────────────────────────────────────────────────────────────────────────────
#  DOCTOR / UNINSTALL
# ─────────────────────────────────────────────────────────────────────────────

def doctor(sess, install_dir: Path) -> int:
    print(bold(f"\n{_g('🩺', '[check]')}  {APP_NAME} — install doctor\n"))
    print(f"  Directory : {install_dir}")
    print(f"  Platform  : {platform_summary()}")
    print()

    problems = []

    if not looks_like_repo(install_dir):
        fail("This directory is not a YouTube AI Agent Studio checkout.")
        return 1
    ok("Source checkout found")

    state_path = install_dir / STATE_FILE
    st = {}
    if state_path.exists():
        try:
            st = json.loads(state_path.read_text(encoding="utf-8"))
            meta = f"  Installed : {st.get('installed_at')}"
            if st.get("commit"):
                meta += f"  (branch {st.get('branch')} @ {st.get('commit')})"
            elif st.get("branch"):
                meta += f"  (branch {st.get('branch')})"
            print(meta)
        except Exception:
            pass
    else:
        warn(f"No {STATE_FILE} — was install.py run here?")

    venv = Path(st["venv"]) if st.get("venv") else install_dir / VENV_DIRNAME
    if not venv_python_path(venv).exists():
        fail("Virtual environment is missing — re-run: python3 install.py")
        return 1
    ok(f"Virtualenv present  {dim(str(venv))}")

    report, out = run_verify(venv, install_dir)
    if not report:
        fail("Verification failed to run:")
        print(tail(out, 25))
        return 1

    for name, version in report["packages"].items():
        if version:
            ok(f"{name:<28} {dim(version)}")
        else:
            fail(f"{name:<28} missing")
            problems.append(name)

    print()
    if report.get("ffmpeg_system"):
        ok(f"ffmpeg (system) {dim(report['ffmpeg_system'])}")
    elif report.get("ffmpeg_binary"):
        ok(f"ffmpeg (bundled with moviepy) {dim(report['ffmpeg_binary'])}")
    else:
        fail("No ffmpeg available")
        problems.append("ffmpeg")

    for key, state in report["keys"].items():
        if state == "set":
            ok(f"{key} set")
        elif key != "ELEVENLABS_API_KEY":
            fail(f"{key} missing")
            problems.append(key)

    for d, present in report["dirs"].items():
        (ok if present else fail)(f"{d}/ {'exists' if present else 'missing'}")
        if not present:
            problems.append(d)

    if report.get("errors"):
        for e in report["errors"]:
            fail(e)

    print()
    if problems:
        fail(f"{len(problems)} problem(s) found: {', '.join(problems)}")
        info("      Fix them by re-running:  python3 install.py --reconfigure")
        return 1
    ok("Everything checks out. Launch with ./start-gui.command"
       if IS_MAC else "Everything checks out.")
    return 0


def uninstall(sess, install_dir: Path) -> int:
    print(bold(f"\n{_g('🧹', '[uninstall]')}  Uninstall {APP_NAME} — {install_dir}\n"))
    venv = install_dir / VENV_DIRNAME
    removed = []

    if venv.exists():
        if sess.ask(f"Delete the virtualenv ({venv})?  ~250 MB", default=True):
            shutil.rmtree(venv, ignore_errors=True)
            removed.append(str(venv))

    for name in ("start-gui.command", "start-gui.sh", "start-gui.bat",
                 "start-pipeline.command", "start-pipeline.sh", "start-pipeline.bat",
                 STATE_FILE):
        path = install_dir / name
        if path.exists():
            path.unlink()
            removed.append(name)

    for name, desc in (("output", "generated videos + images"),
                       ("music library", "your background music tracks")):
        path = install_dir / name
        if path.exists() and any(path.iterdir()):
            if sess.ask(f"Delete {name}/ ({desc})?", default=False):
                shutil.rmtree(path, ignore_errors=True)
                removed.append(f"{name}/")

    if (install_dir / ".env").exists():
        if sess.ask("Delete .env (your API keys)?", default=False):
            (install_dir / ".env").unlink()
            removed.append(".env")

    print()
    if removed:
        ok("Removed: " + ", ".join(removed))
    else:
        info("Nothing removed.")
    info("  The source code was left untouched. Delete the folder manually to remove everything.")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────────

def banner() -> None:
    print()
    print(bold(f"  {_g('🎬', '>>')}  {APP_NAME} — installer"))
    print(dim(f"  fork: {REPO_OWNER}/{REPO_NAME}"))
    rule()


def next_steps(install_dir: Path, venv: Path, sess, report: dict) -> None:
    rel = install_dir.name
    gui_cmd = "./start-gui.command" if IS_MAC else (
        "start-gui.bat" if IS_WIN else "./start-gui.sh")
    arrow  = _g("→", "->")
    bullet = _g("•", "*")
    print()
    rule(_g("═", "="))
    print(bold(f"  {_g('🎉', 'OK')}  Installation complete"))
    rule(_g("═", "="))
    print(f"""
  Launch the studio
      cd {rel if rel != '.' else '.'}
      {gui_cmd}                {dim('# or: source .venv/bin/activate && python gui.py')}
      {dim(arrow + f' http://localhost:{GUI_PORT}')}

  Or run the pipeline straight from the terminal
      ./{gui_cmd.replace('start-gui', 'start-pipeline').lstrip('./')}

  Re-check this install at any time
      python3 install.py --doctor

  Update the fork later
      python3 install.py --upgrade

  Before your first video
      {bullet} Open Settings in the GUI and describe your channel (better topics).
      {bullet} To auto-upload: replace client_secret.json with your Google OAuth
        credentials — see SETUP.md → Step 4.
      {bullet} Drop MP3s in “music library/” for background music (optional).
""")

    missing_keys = [k for k, v in (report or {}).get("keys", {}).items()
                    if v != "set" and k != "ELEVENLABS_API_KEY"]
    if missing_keys:
        warn("No API keys yet — the pipeline cannot run until you add them to .env")
        print(f"      {dim(str(install_dir / '.env'))}")

    if sess.interactive and sess.ask("\n  Launch the studio now?", default=True):
        print()
        try:
            subprocess.run([str(venv_python_path(venv)), "gui.py"], cwd=str(install_dir))
        except KeyboardInterrupt:
            print("\n  Stopped.")


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="install.py",
        description=f"Install {APP_NAME} ({REPO_OWNER}/{REPO_NAME} fork).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  python3 install.py                          install into this checkout
  python3 install.py --dir ~/yt-studio        clone the fork, then install
  python3 install.py --yes                    non-interactive (CI)
  python3 install.py --doctor                 check an existing install
  python3 install.py --upgrade                git pull + reinstall deps
  python3 install.py --uninstall              remove the venv and launchers
""")
    p.add_argument("--dir", default=None,
                   help="where to install (default: this checkout, or ./youtube-agentic-ai-studio)")
    p.add_argument("--repo", default=os.environ.get("YT_STUDIO_REPO", REPO_URL),
                   help=f"git URL to clone (default: {REPO_URL})")
    p.add_argument("--branch", default=os.environ.get("YT_STUDIO_BRANCH", DEFAULT_BRANCH),
                   help=f"branch to clone (default: {DEFAULT_BRANCH})")
    p.add_argument("--source", default=None,
                   help="copy the source from a local checkout instead of cloning")
    p.add_argument("--python", default=None, help="interpreter to build the virtualenv with")
    p.add_argument("--venv-dir", default=None, help=f"virtualenv path (default: <dir>/{VENV_DIRNAME})")
    p.add_argument("-y", "--yes", action="store_true", help="non-interactive; accept defaults")
    p.add_argument("--upgrade", action="store_true", help="git pull and reinstall dependencies")
    p.add_argument("--reconfigure", action="store_true", help="re-prompt for API keys")
    p.add_argument("--no-system-deps", action="store_true",
                   help="never install system packages (ffmpeg, python…); only detect")
    p.add_argument("--no-verify", action="store_true", help="skip the post-install verification")
    p.add_argument("--doctor", action="store_true", help="check an existing install and exit")
    p.add_argument("--uninstall", action="store_true", help="remove the venv, launchers and state")
    p.add_argument("--log-file", default=None, help=f"log path (default: <dir>/{INSTALL_LOG})")
    p.add_argument("-v", "--verbose", action="store_true", help="stream pip/git output live")
    return p.parse_args(argv)


def main(argv=None) -> int:
    global _LOG_PATH
    global _VERBOSE
    args = parse_args(argv)
    _VERBOSE = args.verbose
    sess = Session(args)

    banner()
    print(f"  Platform  : {platform_summary()}")
    print(f"  Installer : {Path(__file__).name}  (Python {'.'.join(str(v) for v in sys.version_info[:2])})")
    if not sess.interactive:
        print(f"  Mode      : {yellow('non-interactive')} {dim('(--yes or no TTY — defaults are accepted)')}")
    print()

    # ── resolve install dir ──────────────────────────────────────────────────
    if args.dir:
        install_dir = Path(args.dir).expanduser().resolve()
    elif looks_like_repo(Path.cwd()):
        install_dir = Path.cwd()
    else:
        install_dir = Path.cwd() / REPO_NAME

    _LOG_PATH = Path(args.log_file).expanduser() if args.log_file else install_dir / INSTALL_LOG
    if not args.log_file and not install_dir.exists():
        _LOG_PATH = Path(tempfile.gettempdir()) / INSTALL_LOG
    log(f"\n=== install.py run {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
    log(f"args: {vars(args)}")

    # ── doctor / uninstall ───────────────────────────────────────────────────
    if args.doctor:
        return doctor(sess, install_dir)
    if args.uninstall:
        return uninstall(sess, install_dir)

    # ── 1 · preflight ────────────────────────────────────────────────────────
    heading("1 / 7  ·  Checking your system")
    if args.no_system_deps:
        info(f"      {dim('(--no-system-deps: only detecting, never installing)')}")

    py = None
    if args.no_system_deps:
        for cand in python_candidates(args.python):
            ver = python_version(cand)
            if ver and ver[:2] >= MIN_PYTHON:
                ok(f"Python {'.'.join(str(v) for v in ver)}  {dim(cand[0])}")
                py = list(cand)
                break
        if py is None:
            fail(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ not found.")
            return 1
        if which("git"):
            ok(f"Git found {dim(which('git'))}")
        else:
            warn("Git not found — will download a source snapshot instead.")
        if which("ffmpeg"):
            ok(f"ffmpeg found {dim(which('ffmpeg'))}")
        else:
            warn("ffmpeg not found — moviepy ships its own, so rendering still works.")
    else:
        py = ensure_python(sess, args.python)
        if py is None:
            fail(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required to continue.")
            return 1
        git_version(sess)

    # ── 2 · source ───────────────────────────────────────────────────────────
    heading("2 / 7  ·  Getting the source")
    ok_src, fresh = acquire_source(sess, install_dir, args.repo, args.branch, args.source)
    if not ok_src:
        return 1
    install_dir = install_dir.expanduser().resolve()
    if not looks_like_repo(install_dir):
        fail(f"{install_dir} does not look like a {APP_NAME} checkout.")
        return 1

    _LOG_PATH = Path(args.log_file).expanduser() if args.log_file else install_dir / INSTALL_LOG
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    # ── 3 · venv + pip ───────────────────────────────────────────────────────
    heading("3 / 7  ·  Creating the virtual environment")
    venv = Path(args.venv_dir).expanduser().resolve() if args.venv_dir \
        else install_dir / VENV_DIRNAME
    if not create_venv(sess, py, venv):
        return 1

    heading("4 / 7  ·  Installing Python dependencies")
    req = install_dir / "requirements.txt"
    if not req.exists():
        fail("requirements.txt not found — is this the right repo?")
        return 1
    if not pip_install(sess, venv, req, upgrade=args.upgrade):
        return 1

    # ── ffmpeg (after deps so we can mention moviepy's bundled binary) ───────
    heading("5 / 7  ·  Checking ffmpeg")
    if args.no_system_deps:
        if which("ffmpeg"):
            ok(f"ffmpeg found {dim(which('ffmpeg'))}")
        else:
            warn("ffmpeg not on PATH (skipped — --no-system-deps).")
    else:
        ensure_tool(sess, "ffmpeg", "ffmpeg", required=False,
                    skip_hint="MoviePy bundles its own ffmpeg build, so video "
                              "rendering works without the system one.")

    # ── 4 · configure ────────────────────────────────────────────────────────
    heading("6 / 7  ·  Configuring API keys")
    configure_env(sess, install_dir)
    scaffold(install_dir)
    make_launchers(install_dir)
    save_state(install_dir, venv, py, args.repo, args.branch)

    # ── 6 · verify ───────────────────────────────────────────────────────────
    report = None
    if not args.no_verify:
        report, out = run_verify(venv, install_dir)
        if not print_report(install_dir, venv, report, sess):
            warn("Install finished with warnings — see above.")
            if report is None:
                print(tail(out, 25))
    else:
        info("\n  Skipping verification (--no-verify).")

    if report and not args.no_verify:
        verify_api_keys(venv, install_dir, read_env(install_dir / ".env"), sess)

    next_steps(install_dir, venv, sess, report)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(f"\n\n  {yellow('Cancelled.')} Nothing was harmed — re-run install.py anytime.\n")
        sys.exit(130)
