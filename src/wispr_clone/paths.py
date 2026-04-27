"""Path resolution for both dev runs and PyInstaller-bundled executables.

Two distinct concepts:

- *Bundled resources* (read-only, ship with the app): icons, default
  dictionary template, etc. In a PyInstaller bundle these live under
  `sys._MEIPASS`. In dev they live next to the source tree.
- *User data* (read-write, survives rebuilds): config.toml, dictionary.txt,
  log file. These live under %APPDATA%/wispr-clone/ on Windows. In dev,
  if APPDATA is not set, we fall back to the project root.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "wispr-clone"


def resource_path(relative: str | os.PathLike[str]) -> Path:
    """Resolve a path to a *bundled, read-only* resource.

    PyInstaller extracts bundled data to a temp dir whose path it stores in
    `sys._MEIPASS`. In dev, we resolve relative to the project root (two
    levels up from this file: src/wispr_clone/paths.py → repo root).
    """
    rel = Path(relative)
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / rel
    # paths.py is at <repo>/src/wispr_clone/paths.py
    return Path(__file__).resolve().parent.parent.parent / rel


def user_data_dir() -> Path:
    """Return the per-user data dir, creating it if missing.

    Uses %APPDATA%\\wispr-clone on Windows. Falls back to the project root
    when APPDATA is unset (typically only in dev/test environments)."""
    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        base = Path(appdata) / APP_NAME
    else:
        # Dev fallback: project root next to source tree.
        base = Path(__file__).resolve().parent.parent.parent
    base.mkdir(parents=True, exist_ok=True)
    return base


def user_config_path() -> Path:
    return user_data_dir() / "config.toml"


def user_dictionary_path(lang: str = "en") -> Path:
    """Per-language custom-vocabulary file. `en` and `yue` are the supported
    languages today; anything else still resolves to a `dictionary-<lang>.txt`
    file so adding a new language is a one-line change."""
    return user_data_dir() / f"dictionary-{lang}.txt"


def legacy_dictionary_path() -> Path:
    """Pre-bilingual single-file location, kept only for one-time migration."""
    return user_data_dir() / "dictionary.txt"


def user_log_path() -> Path:
    return user_data_dir() / "wispr-clone.log"


def user_usage_log_path() -> Path:
    """Append-only JSONL of per-dictation usage records (count, audio s,
    chars, cost). One line per take. Used by the tray's Show usage dialog."""
    return user_data_dir() / "usage.jsonl"
