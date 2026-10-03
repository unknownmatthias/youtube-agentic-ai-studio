# 📦 Installer — one-command setup

Set up this fork of **YouTube AI Agent Studio** without touching a requirements file by
hand. The installer creates an isolated virtualenv, installs every dependency, asks for
your API keys (hidden as you type), and leaves you double-clickable launchers.

> Works on **macOS** (primary target), **Linux** and **Windows**.
> Time required: **~3 minutes**, plus ~2 minutes of key-copying.

---

## 🍎 macOS

Pick whichever you prefer — both do the same thing.

### Option A — one command in Terminal

```bash
curl -fsSL https://raw.githubusercontent.com/unknownmatthias/youtube-agentic-ai-studio/main/install.sh | bash
```

### Option B — double-click

Download the repo, then double-click **`install.command`**
(right-click → *Open* the first time if macOS complains about an unidentified developer,
or run `xattr -d com.apple.quarantine install.command`).

### Then

```bash
./start-gui.command          # or: source .venv/bin/activate && python gui.py
```

A browser window opens at **http://localhost:7070**.

---

## 🐧 Linux

```bash
curl -fsSL https://raw.githubusercontent.com/unknownmatthias/youtube-agentic-ai-studio/main/install.sh | bash
cd youtube-agentic-ai-studio && ./start-gui.sh
```

## 🪟 Windows (PowerShell)

```powershell
irm https://raw.githubusercontent.com/unknownmatthias/youtube-agentic-ai-studio/main/install.py -OutFile install.py
python install.py
start-gui.bat
```

---

## 🧰 Already have a clone?

```bash
cd youtube-agentic-ai-studio
python3 install.py            # installs into the current directory
```

---

## What the installer does

| # | Step | Details |
|---|---|---|
| 1 | **Preflight** | Finds a Python ≥ 3.10 (`/opt/homebrew`, `/usr/local`, pyenv, `PATH`…). On macOS it offers `brew install python@3.12` if the system Python is the ancient 3.9. |
| 2 | **Source** | Clones the fork, updates an existing clone with `git pull`, or downloads a tarball if git isn't installed. |
| 3 | **Virtualenv** | Creates `.venv/` (never touches your system Python). |
| 4 | **Dependencies** | `pip install -r requirements.txt` with pip pre-upgraded. |
| 5 | **ffmpeg** | Detects it; offers `brew install ffmpeg` (or apt/dnf/winget) when missing. Optional — MoviePy ships its own ffmpeg, so rendering works either way. |
| 6 | **API keys** | Prompts for Gemini + Pexels (+ optional ElevenLabs), writes `.env` with `chmod 600`, and can verify each key with a live call. |
| 7 | **Verify** | Imports every dependency, resolves the ffmpeg binary, imports `config.py`, checks folders and the GUI port. Prints a report. |

It also creates `output/`, `output/images/`, `music library/` and the launcher scripts.

---

## Options

```bash
python3 install.py --help
```

| Flag | What it does |
|---|---|
| `--dir PATH` | Where to install (default: this checkout, else `./youtube-agentic-ai-studio`) |
| `--branch NAME` | Branch to clone (default `main`) |
| `--repo URL` | Clone from a different remote |
| `--source PATH` | Copy the source from a local checkout instead of cloning (offline installs) |
| `--python PATH` | Interpreter used to build the virtualenv |
| `--venv-dir PATH` | Put the virtualenv somewhere else |
| `-y`, `--yes` | Non-interactive: accept every default (CI / scripted installs) |
| `--upgrade` | `git pull` + reinstall dependencies |
| `--reconfigure` | Re-prompt for API keys |
| `--no-system-deps` | Only detect system tools, never install them |
| `--no-verify` | Skip the post-install checks |
| `--doctor` | Diagnose an existing install and exit |
| `--uninstall` | Remove the virtualenv, launchers and generated files |
| `-v`, `--verbose` | Stream git/pip output live |

### Non-interactive / CI

Keys are taken from the environment when it isn't attached to a terminal:

```bash
GEMINI_API_KEY=... PEXELS_API_KEY=... python3 install.py --yes --dir ~/yt-studio
```

### Keeping it up to date

```bash
python3 install.py --upgrade     # git pull + pip install -r requirements.txt
python3 install.py --doctor      # is everything still healthy?
python3 install.py --uninstall   # remove venv + launchers (source stays)
```

---

## Files it creates

| Path | Committed? | Purpose |
|---|---|---|
| `.venv/` | ❌ gitignored | Isolated Python environment |
| `.env` | ❌ gitignored | Your API keys (`chmod 600`) |
| `output/`, `output/images/` | ❌ gitignored | Generated videos and images |
| `music library/` | ✅ (`.gitkeep`) | Drop MP3/WAV background tracks here |
| `start-gui.command`, `start-gui.sh`, `start-gui.bat` | ❌ gitignored | Launch the dashboard |
| `start-pipeline.command`, `start-pipeline.sh`, `start-pipeline.bat` | ❌ gitignored | Run the CLI pipeline |
| `.install-state.json` | ❌ gitignored | Used by `--doctor` / `--upgrade` |
| `install.log` | ❌ gitignored | Full transcript of the last run |

---

## API key precedence

Keys can live in three places. First non-empty value wins:

1. the literal in **`config.py`** (this is what the GUI's *Save settings* writes)
2. a real **environment variable**
3. **`.env`** next to `config.py` (what the installer writes)

Clear the value in `config.py` if you want `.env` to win.
*(Older versions of this project documented `.env` but never actually read it — that's
fixed in `config.py`.)*

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `Python 3.9.x` on macOS | That's the Xcode system Python. Let the installer run `brew install python@3.12`, or install from python.org. |
| `brew: command not found` | Install Homebrew: `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"` |
| ffmpeg install fails | Not fatal — MoviePy bundles its own build. Re-run `brew install ffmpeg` whenever you like. |
| `could not create venv` (Linux) | `sudo apt install python3-venv` (the installer offers to do it). |
| Port 7070 already in use | Quit the other Studio instance, or change `port` at the bottom of `gui.py`. |
| GUI starts but keys are ignored | Check `.env` for typos, and make sure `config.py` doesn't still hold a literal key. `python3 install.py --reconfigure`. |
| Downloads blocked by a proxy | Set `HTTPS_PROXY` first; pip and the installer both honour it. |
| `install.command` "cannot be opened" | Right-click → **Open**, or `xattr -d com.apple.quarantine install.command`. |
| Something else | Read `install.log` in the install directory and open an issue with the last 20 lines. |

---

Prefer the manual route? See **[SETUP.md](SETUP.md)**.
