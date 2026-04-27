# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`wispr-clone` is a personal Wispr-Flow-style dictation tool: hold a global hotkey, speak, release — the transcript (via Groq Whisper REST) is pasted into the focused app. Windows-only.

## Runtime / environment (read first)

This project targets **Windows-native Python**, not WSL. The dependencies (`keyboard`, `pystray`, `pyperclip`, `sounddevice`) need real Win32 APIs; a WSL Linux venv silently installs Linux wheels that crash or no-op at runtime. Before writing or running any code, verify the active Python is Windows:

```powershell
python -c "import sys; print(sys.executable)"
```

The path must start with a Windows drive letter (`E:\`, `C:\`, …). If it shows `/usr/...` or `/home/...`, stop and recreate the venv from PowerShell (`py -m venv .venv` or `uv venv`).

In any plans, READMEs, or instructions, use **Windows path syntax** (`E:\all_repo\wispr_clone\...`), not the WSL mount form (`/mnt/e/...`) — the user runs and edits this from native Windows.

## Common commands

All commands are intended to run from **Windows PowerShell** in the project root with the venv activated.

```powershell
.\.venv\Scripts\Activate.ps1

# install (editable + dev)
uv sync                              # or: pip install -e ".[dev]"

# run the app
python -m wispr_clone.main           # canonical entrypoint
wispr-clone                          # console script (same thing)
python main.py                       # passthrough at repo root

# tests
pytest tests/
pytest tests/test_post_process.py            # single file
pytest tests/test_config.py::test_save_then_load_round_trip   # single test
pytest -k "filler"                            # by keyword
```

Test suite must stay free of Win32 / Groq calls. The HUD smoke test auto-skips when no display is available.

## Architecture (the parts that span files)

### Threading model — three threads, strict ownership

The app interleaves Tkinter, the `keyboard` library's listener, and HTTP/paste work. Mixing them up is the easiest way to introduce hangs or races.

1. **Tk main thread** (process main thread) owns `tk_root`, the HUD, the tray-menu callbacks' Tk side, and all UI state mutation. `tk_root.mainloop()` runs here. Tk objects must only be touched from this thread.
2. **`keyboard` listener thread** (created by the `keyboard` library) fires `Controller.on_press` / `on_release`. These callbacks **must not** touch Tk directly — they marshal back to the Tk thread via `root.after(0, ...)`.
3. **Worker thread** — a single-worker `ThreadPoolExecutor` inside `Controller`. It runs the Groq HTTP call and the paste keystroke. UI updates from the worker also marshal back via `root.after(0, ...)`.

`pystray` runs on its own detached thread (`Tray.run_detached()`); its menu callbacks bounce back into the Tk thread via `tk_root.after(0, ...)` before doing anything UI-y.

When adding new behavior, identify which thread you're on and either stay there or marshal — never cross-thread mutate.

### State machine — `Controller` is the single source of truth

`IDLE → RECORDING → TRANSCRIBING → IDLE`. Transitions are guarded by a `threading.Lock` so two fast hotkey presses don't race. Recording auto-stops at `max_recording_seconds`. Errors at any stage call `_reset_to_idle()` and surface via the `on_error` callback (which produces a tray balloon notification). Empty audio / empty transcript silently resets to IDLE.

The state callback drives the tray icon color (idle / recording / processing); the HUD has its own two visual states (`recording` shows the meter; `transcribing` swaps to a yellow dot + label).

### Audio pipeline

`AudioCapture` (sounddevice `InputStream`, mono float32 → int16) buffers full-recording frames and a rolling 32-chunk window for the live meter. `get_current_level()` computes RMS over the most recent ~50 ms, normalized against `LEVEL_RMS_REFERENCE`. On stop, frames are encoded as a single in-memory WAV (PCM_16) via `soundfile` and handed to `Transcriber.transcribe`, which uploads to Groq's `whisper-large-v3-turbo` with `response_format="text"` and an optional `prompt` from the dictionary.

The custom dictionary (`dictionary.txt`) is reloaded on every press so edits take effect without a restart. `build_prompt` truncates at a ~800-char budget on a term boundary because Whisper's prompt has a ~244-token limit.

`post_process.strip_fillers` is conservative regex-only: only word-boundary `um/uh/er/erm/ah` (and stretched variants) are removed; punctuation/spacing is tidied; the first letter is recapitalized.

### Paste

`paste.paste()` is clipboard-with-restore: save current clipboard → set transcript → 50 ms propagation sleep → send Ctrl+V via `keyboard.send` → wait `clipboard_restore_delay_ms` (default 150 ms) so the destination app actually consumes the paste → restore previous clipboard. The propagation delay matters because Windows clipboard writes are asynchronous; pasting too soon after `pyperclip.copy` can paste stale content.

### Hotkey + dialog interaction

`HotkeyListener` registers on the trigger key (last token of the combo) and verifies modifiers manually on each event so `keyboard.on_press_key` can fire on hold-to-record. `HotkeyDialog` **stops** the main listener while open so the capture loop can grab any combo without firing dictation; saving calls `set_combo()` (stop + restart with the new combo) and persists via `save_config`. Cancel restores the previous listener.

### Process exit

`pystray`'s detached thread keeps a hidden Win32 window alive even after `icon.stop()`. `main.py` ends with `os._exit(0)` to actually terminate the process. Don't replace this with `sys.exit()` — the user-facing **Quit** menu item will appear to do nothing.

### Config

`config.py` defines `Config` (frozen dataclass-ish) with `from_dict` that **clamps and validates** all fields (`max_recording_seconds` 1–600, `sample_rate` whitelisted, `clipboard_restore_delay_ms` 0–5000, hotkey lowercased, blanks fall back to defaults). Always go through `from_dict` so user edits to `config.toml` can't crash startup.

### Paths — user data vs. bundled resources

`paths.py` is the single source of truth for filesystem layout:

- **User data** (`config.toml`, `dictionary.txt`, `wispr-clone.log`, optional `.env`) lives in `%APPDATA%\wispr-clone\`. `user_data_dir()` creates the directory on first call. This means edits survive `dist/` rebuilds and the bundled folder stays clean.
- **Bundled resources** (icons / templates under `assets/`) are loaded via `resource_path()`, which checks `sys._MEIPASS` (set by PyInstaller at runtime) and falls back to a project-root-relative path in dev. Always go through this helper for asset loads.
- **`.env` discovery** in `main._find_env_path` checks (in order): next to the executable for a frozen build, project root in dev, then `%APPDATA%\wispr-clone\` as a fallback.

### Packaging (PyInstaller)

`build.ps1` produces a one-folder windowed bundle at `dist\wispr-clone\wispr-clone.exe`. Required flags: `--windowed`, `--add-data "assets;assets"`, plus `--hidden-import PIL._tkinter_finder` and `--hidden-import tkinter` (Pillow + Tk under PyInstaller need explicit hidden-imports). `pyinstaller` lives in the `[dev]` extra. If you add a new bundled asset folder, also add a matching `--add-data` entry in `build.ps1`.

## Scope fences (do not relax without asking)

- The **HUD** is deliberately minimal: Tkinter only, fixed bottom-center on the primary monitor, no cursor-follow, no multi-monitor logic, no animations beyond the meter bar and a short fade. No spectrum analyzer, waveform, pulsing dot, or theming. Expanding the HUD is a v2 concern.
- One Groq Whisper model (`whisper-large-v3-turbo`) over REST. No on-device inference, no model switching, no streaming.
- No new top-level dependencies without a clear need. The current set is small on purpose.

## Useful files for orientation

- `src/wispr_clone/main.py` — entrypoint and dependency wiring; the cleanest place to trace what talks to what.
- `src/wispr_clone/controller.py` — state machine; read this before changing recording/transcription flow.
- `README.md` — user-facing setup, troubleshooting, and config reference.
