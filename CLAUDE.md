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

`IDLE → RECORDING → TRANSCRIBING → IDLE`. Transitions are guarded by a `threading.Lock` so two fast hotkey presses don't race. The active language is captured at the moment the press lock is acquired (`_active_language`); the worker thread reads it for dictionary path + Whisper language. A second press in either language while non-IDLE is ignored. Recording auto-stops at `max_recording_seconds`. Errors at any stage call `_reset_to_idle()` and surface via `on_error` (tray balloon notification). Empty audio / empty transcript silently resets to IDLE.

The state callback drives the tray icon color (idle / recording / processing); the HUD has two visual states (`recording` shows the meter; `transcribing` swaps to a yellow dot + label) and tints the recording dot per language (red for English, blue for Cantonese — same `METER_COLOR` so we don't introduce a brand-new hue).

### Audio pipeline

`AudioCapture` (sounddevice `InputStream`, mono float32 → int16) buffers full-recording frames and a rolling 32-chunk window for the live meter. `get_current_level()` computes RMS over the most recent ~50 ms, normalized against `LEVEL_RMS_REFERENCE`. On stop, frames are encoded as a single in-memory WAV (PCM_16) via `soundfile` and handed to `Transcriber.transcribe`, which uploads to Groq's `whisper-large-v3-turbo` with `response_format="text"`, an optional language code, and an optional prompt built from the per-language dictionary plus (for Cantonese) the `CANTONESE_PRIMING` seed.

**Whisper language parameter:** `whisper_code(EN)` returns **None** (auto-detect) on purpose. Passing `language="en"` to the transcriptions endpoint causes Whisper to translate non-English audio into English text — a surprising side effect for a dictation tool. Auto-detect leaves English audio as English and routes Cantonese-on-English-hotkey to Chinese output (so the wrong-hotkey case is obvious instead of silently translated).

`whisper_code(YUE)` returns `"yue"` (ISO-639-3 — Whisper-large-v3 has explicit Cantonese training). `Transcriber` keeps a sticky `_LANGUAGE_FALLBACKS` table: if Groq rejects `yue` with a "language … invalid" 4xx, the call retries once with `"zh"` and remembers the fallback for the rest of the session.

The Cantonese register problem: with `language="zh"` Whisper tends to render Cantonese audio as **Standard Written Chinese** (書面語: 我們, 的, 了, 東西), which loses the spoken-Cantonese register the user actually said. Even with `language="yue"` the model can drift. `CANTONESE_PRIMING` (in `dictionary.py`) is the strongest mitigation — it's a dense colloquial-Cantonese sample (我哋, 嘅, 咗, 嘢, 喎, 啦, 㗎, 嗰陣) that sets register because Whisper's prompt field is *previous-text context*. Continue in the same style. Do NOT replace it with an instruction sentence ("please transcribe in …") — Whisper interprets prompts as context, so directives confuse the model.

Per-language dictionaries (`dictionary-en.txt`, `dictionary-yue.txt`) are reloaded on every press so edits take effect without a restart. `build_prompt(terms, prefix=...)` truncates at a ~800-char budget on a term boundary because Whisper's prompt has a ~244-token limit. The Cantonese priming sample is prepended via `prefix=` and counted against the same budget.

`post_process.strip_fillers(text, lang)` is conservative regex-only. English: word-boundary `um/uh/er/erm/ah` (+ stretched). Cantonese: global `嗯+/呃+/噉+` plus literal `即係/嗰個/係呢個`. Sentence-final `啊` is intentionally **not** stripped — it carries meaning. Casing is restored only for English; CJK has no case. There is no register-conversion pass — Cantonese register relies entirely on `language="yue"` plus the priming prompt; deterministic substitution tables (e.g. 為什麼→點解) were tried and rejected as too lossy.

### Smart cleanup (`structure.py`)

Optional, gated, runtime-toggleable. Pipeline position: `Whisper → strip_fillers → apply_structure → paste`. `apply_structure` is a no-op when `controller._smart_cleanup_enabled` is False. When enabled it tries three paths in order, returning the original text if none succeed:

1. **`_split_ordinal_list`** — deterministic regex splitter. Matches 3+ ordinals in canonical sequence: `first/second/third` (or `fourth/fifth`), or clause-anchored `one/two/three` (count-words must follow `,`/`.`/`:`/`;` or start-of-text after the first one), or Cantonese `第一/第二/第三`. Carves out segments between markers; per-segment cleanup peels a leading pronoun (`you/we/i/they/it`) and a leading aux verb (`need/needs/have/has/should/can/must/are/is/will/would/then/and/so/also/to/the` — **not** `do/does/did`, those carry content). Optional intro before the first ordinal becomes a "Title:" line. Output: numbered list. No LLM call.
2. **`_split_comma_list`** — 3+ comma-separated parts where every part is ≤15 chars after stripping. Long preambles disqualify (too risky to deterministically separate intro from items). Output: bulleted list. No LLM call.
3. **LLM fallback** — gated by `should_structure(text, lang)` (the existing scoring heuristic — ≥2 of: ordinal run, trigger phrase, 3+ short clauses). Calls `structure_text` against the injected Groq client (reusing `Transcriber.client` — no second auth) with a **relaxed** system prompt that explicitly permits dropping verbal ordinals + lead-ins (still forbids paraphrase/translation). Result is validated via `_validate_cleaned`: length ratio 0.7–1.3× plus a token-set check that excludes `_DROPPABLE_TOKENS` (ordinals, pronouns, aux verbs) before computing the 15 % missing-token threshold. On rejection/timeout/exception → original text.

The tray's "Smart cleanup" toggle calls `Controller.set_smart_cleanup(bool)` which persists via `save_config` so the choice survives restart.

Do not re-tighten the system prompt to "preserve every word" — the relaxed prompt is what makes ordinal-drop outputs (e.g. `1. garlic / 2. salt / 3. pepper`) achievable when the LLM is reached. Do not add `do/does/did` to the lead-in regex or the droppable token set — they appear as content verbs in dictation ("first do the build").

### Paste

`paste.paste()` is clipboard-with-restore: save current clipboard → set transcript → 50 ms propagation sleep → send Ctrl+V via `keyboard.send` → wait `clipboard_restore_delay_ms` (default 150 ms) so the destination app actually consumes the paste → restore previous clipboard. The propagation delay matters because Windows clipboard writes are asynchronous; pasting too soon after `pyperclip.copy` can paste stale content.

### Hotkey + dialog interaction

Two `HotkeyListener` instances run in parallel — one for English, one for Cantonese — each calling language-tagged controller methods (`on_press_en` / `on_press_yue` etc.). Each listener registers on the trigger key (last token of the combo) and verifies modifiers manually so `keyboard.on_press_key` can fire on hold-to-record. `HotkeyDialog` accepts which `Config` field it edits (`"hotkey_english"` or `"hotkey_cantonese"`) and which listener to restart; it **stops** that listener while open so the capture loop can grab any combo without firing dictation, then `set_combo()`s on save (stop + restart with the new combo) and persists via `save_config`. Cancel restores the listener.

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
