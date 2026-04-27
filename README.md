# wispr-clone

Personal Wispr-Flow-style dictation tool for Windows. Hold a hotkey, speak, release — the transcription is pasted into the focused app via Groq Whisper.

- Hold-to-record global hotkey (configurable from the tray menu)
- Live mic-level meter HUD pinned to the bottom-center of the primary monitor
- Custom-vocabulary biasing via `dictionary.txt`
- Conservative filler-word stripping (`um`, `uh`, `er`, `erm`, `ah`)
- Clipboard-with-restore paste — your previous clipboard contents are put back after the paste

## Requirements

- Windows 10 or 11
- Python 3.13+ **Windows-native** (not WSL — the `keyboard`, `pystray`, and `pyperclip` libs need real Win32 APIs)
- Microphone
- Groq API key — https://console.groq.com

## Install

From **Windows PowerShell** in the project root:

```powershell
cd E:\all_repo\wispr_clone
py -m venv .venv                    # or: uv venv
.\.venv\Scripts\Activate.ps1
uv sync                             # or: pip install -e ".[dev]"
```

Verify the venv is Windows Python (this is the most common setup mistake):

```powershell
python -c "import sys; print(sys.executable)"
```

The path must start with a Windows drive letter (`E:\`, `C:\`, …). If it starts with `/usr/...` or `/home/...`, you created the venv from WSL — recreate it from PowerShell.

Copy `.env.example` to `.env` and paste your Groq API key. For dev runs the `.env` lives at the project root; for the bundled `.exe` it should live next to the executable (`dist\wispr-clone\.env`) **or** at `%APPDATA%\wispr-clone\.env`.

```powershell
copy .env.example .env
notepad .env
```

## Run

```powershell
python -m wispr_clone.main
```

Or use the installed console script:

```powershell
wispr-clone
```

A grey microphone icon appears in the system tray. Default hotkey is **F9** — hold to record, release to transcribe.

While holding the hotkey:

1. A small HUD shows at the bottom of the primary monitor with a red dot and a live mic-level meter.
2. On release, the dot turns yellow and the label reads "Transcribing…".
3. Once Groq returns, the text is pasted into the focused app and the HUD fades out.

The tray icon's color reflects the current state: grey (idle), red (recording), yellow (transcribing).

## User data location

`config.toml`, `dictionary.txt`, and `wispr-clone.log` live in:

```
%APPDATA%\wispr-clone\
```

(typically `C:\Users\<you>\AppData\Roaming\wispr-clone\`). This directory is created on first run with default contents. Storing user data here means edits survive `dist/` rebuilds and the bundled folder stays clean.

You can open it quickly: Press **Win+R**, type `%APPDATA%\wispr-clone`, hit Enter.

The `.env` (Groq API key) is loaded from one of:
- `.env` next to the running `.exe` (for the bundled build)
- `.env` in the project root (for dev runs)
- `%APPDATA%\wispr-clone\.env` (always checked as a fallback)

## Configuration

`config.toml` is created on first run with these defaults:

```toml
hotkey = "f9"
max_recording_seconds = 90
sample_rate = 16000
mic_device = ""
clipboard_restore_delay_ms = 150
```

| Key | Notes |
| --- | --- |
| `hotkey` | Any combo `keyboard` accepts: `f9`, `ctrl+space`, `ctrl+shift+d`, `right alt`, etc. Easiest to set via the tray menu. |
| `max_recording_seconds` | Auto-stop recording after this many seconds (clamped to 1–600). |
| `sample_rate` | Mic sample rate in Hz. 16 kHz is plenty for Whisper. |
| `mic_device` | Empty = system default. Otherwise a substring of the device name (e.g. `"Realtek"`). |
| `clipboard_restore_delay_ms` | How long to wait after Ctrl+V before restoring the previous clipboard contents. |

### Tray menu

- **Configure hotkey…** — opens a small dialog. Press your new combo, then click **Save**.
- **Edit dictionary…** — opens `dictionary.txt` in the system default editor (Notepad on Windows).
- **Quit** — fully shuts down the app.

### Custom dictionary

`dictionary.txt` biases transcription toward your jargon, names, and acronyms. One term per line; lines starting with `#` are comments.

```
# names
Tamcho
Anthropic
# jargon
CTranslate2
SendInput
```

Edits take effect on the next dictation press — no restart required. The dictionary is sent to Whisper as a `prompt`, which has a token budget; we truncate at ~800 characters on a term boundary.

### Filler-word stripping

The default blocklist (`um`, `uh`, `er`, `erm`, `ah` and stretched variants like `umm`, `uhh`) is removed from every transcript before paste. Spacing and punctuation around the removed words are tidied; the first letter is recapitalized. Words that merely *contain* a filler (`umbrella`, `humble`) are left alone.

## Project structure

```
src/wispr_clone/
    main.py               # entrypoint: wires up Tk, tray, hotkey, controller
    controller.py         # state machine: IDLE → RECORDING → TRANSCRIBING → IDLE
    audio_capture.py      # sounddevice → in-memory WAV bytes + level meter
    transcribe.py         # Groq Whisper REST client
    paste.py              # clipboard-with-restore paste
    post_process.py       # filler-word stripping + tidy
    dictionary.py         # custom-vocabulary loading
    hud.py                # frameless Toplevel + mic-level meter
    tray.py               # pystray icon + menu
    hotkey.py             # global hold-to-record hotkey listener
    hotkey_dialog.py      # tray-triggered hotkey capture dialog
    config.py             # config + .env loading, validation, persistence
tests/                    # pytest suite (no Win32 / no Groq calls)
```

## Logging

Runtime logs are written to `%APPDATA%\wispr-clone\wispr-clone.log`. The log is appended on every run. If something misbehaves, this is the first place to look.

## Build a standalone .exe

```powershell
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"           # ensures pyinstaller is available
.\build.ps1
```

This produces a one-folder bundle at `dist\wispr-clone\wispr-clone.exe`. The folder contains the executable plus its dependencies — copy or move the whole folder if you relocate it. The build is `--windowed` so no console window appears at runtime.

If PyInstaller complains about missing modules at runtime, add them to the `--hidden-import` list in `build.ps1`.

## Run at login

After a successful build:

1. Press **Win+R**, type `shell:startup`, hit **Enter**. Explorer opens your per-user Startup folder (`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`).
2. In a second Explorer window, navigate to `dist\wispr-clone\` inside this project.
3. **Right-click** `wispr-clone.exe` → **Send to** → **Desktop (create shortcut)** — or hold **Alt** and drag-drop into the Startup folder to create a shortcut directly. Move the shortcut into the Startup folder if you went via the desktop.
4. Sign out and back in (or reboot) to confirm the tray icon appears on its own.

If you want to skip the sign-in/out, double-click the shortcut once to verify it launches cleanly.

### Antivirus warnings

The first time you run an unsigned PyInstaller `.exe`, Windows SmartScreen may show:

> Windows protected your PC

Click **More info** → **Run anyway**. Microsoft Defender (or your AV) may also quarantine the executable on first launch — PyInstaller binaries trip a lot of generic heuristics.

If Defender keeps deleting `wispr-clone.exe`, add a folder exclusion:

1. Open **Windows Security** → **Virus & threat protection** → **Manage settings** under "Virus & threat protection settings".
2. Scroll to **Exclusions** → **Add or remove exclusions** → **Add an exclusion** → **Folder**.
3. Pick the full path to your `dist\wispr-clone\` folder (e.g. `E:\all_repo\wispr_clone\dist\wispr-clone`).

Keep this exclusion narrow — exclude only the bundle folder, not your whole drive.

## Troubleshooting

**Hotkey doesn't fire.** Some Windows configurations require the host process to be elevated for `keyboard` to capture system-wide keys. Run PowerShell as Administrator and re-launch.

**Tray icon never appears.** Check that no other instance is already running (the app does not currently single-instance itself). Kill stray `python.exe` processes from Task Manager and try again.

**"GROQ_API_KEY is not set".** You either haven't created `.env`, or you left the placeholder value (`your_groq_api_key_here`). Paste your real key. For the bundled `.exe`, place `.env` next to `wispr-clone.exe` or in `%APPDATA%\wispr-clone\`.

**Mic error / no audio.** Open Windows Sound settings and confirm the input device works. If you have multiple microphones, set `mic_device` in `config.toml` to a substring of the device name.

**Clipboard ate my copy.** A paste briefly takes over the clipboard. By default we restore your previous content after 150 ms. If you press Ctrl+C during that window, the restore will overwrite your copy. Increase `clipboard_restore_delay_ms` if this trips you up.

**Transcript is wrong on a name or acronym.** Add it to `dictionary.txt`. Re-press your hotkey — no restart needed.

**Recording cuts off at 90 s.** Increase `max_recording_seconds` in `config.toml` (max 600 s). For very long sessions the Groq REST upload becomes the bottleneck; keep individual takes short.

## Development

```powershell
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest tests/
```

The HUD smoke test skips automatically when no display is available; everything else runs anywhere.

## Scope (v1)

The HUD is deliberately minimal: Tkinter only, fixed bottom-center on the primary monitor, no cursor-following, no multi-monitor logic, no animations beyond the meter bar and a short fade. Expanding the HUD beyond this is a v2 concern.

The app talks to **one** Groq Whisper model (`whisper-large-v3-turbo`) over their REST API — no on-device inference, no model switching, no streaming.
