"""wispr-clone entrypoint. Tk owns the main thread; pystray runs detached."""
from __future__ import annotations

import logging
import sys
import tkinter as tk
from pathlib import Path

from .config import Config, load_config, load_groq_api_key
from .controller import Controller, State
from .hotkey import HotkeyListener
from .hotkey_dialog import HotkeyDialog
from .hud import HUD
from .paths import (
    legacy_dictionary_path,
    user_config_path,
    user_data_dir,
    user_dictionary_path,
    user_log_path,
)
from .tray import Tray
from .transcribe import Transcriber


def _configure_logging(log_path: Path) -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Avoid duplicate handlers on re-entry.
    for h in list(root.handlers):
        root.removeHandler(h)
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.addHandler(stream)
    try:
        file_h = logging.FileHandler(log_path, encoding="utf-8")
        file_h.setFormatter(fmt)
        root.addHandler(file_h)
    except OSError:
        pass


_EN_DICT_TEMPLATE = (
    "# English custom vocabulary for Whisper biasing.\n"
    "# One term per line. Lines starting with # are comments.\n"
    "# Example:\n"
    "# Tamcho\n"
    "# Anthropic\n"
    "# CTranslate2\n"
)

_YUE_DICT_TEMPLATE = (
    "# Cantonese custom vocabulary for Whisper biasing.\n"
    "# One term per line. Lines starting with # are comments.\n"
    "# Common Cantonese particles are already primed in the prompt seed,\n"
    "# so add only proper names, jargon, or local words you use often.\n"
    "# Example:\n"
    "# 譚仔\n"
    "# 港鐵\n"
    "# 茶餐廳\n"
)


def _ensure_dictionaries(en_path: Path, yue_path: Path) -> None:
    """Bootstrap per-language dictionary files. Migrates the legacy
    single `dictionary.txt` to `dictionary-en.txt` on first run if the
    English file does not yet exist."""
    legacy = legacy_dictionary_path()
    if legacy.exists() and not en_path.exists():
        try:
            legacy.rename(en_path)
        except OSError:
            # Fall back to a copy if rename fails (e.g. cross-device).
            en_path.write_bytes(legacy.read_bytes())
    if not en_path.exists():
        en_path.write_text(_EN_DICT_TEMPLATE, encoding="utf-8")
    if not yue_path.exists():
        yue_path.write_text(_YUE_DICT_TEMPLATE, encoding="utf-8")


def _find_env_path() -> Path:
    """Look for .env next to the executable / project root, then in user data dir.

    For the bundled .exe we accept either: the user dropping .env next to the
    executable (simplest), or .env inside %APPDATA%\\wispr-clone\\."""
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / ".env")
    else:
        candidates.append(Path.cwd() / ".env")
    candidates.append(user_data_dir() / ".env")
    for p in candidates:
        if p.exists():
            return p
    # Return the first candidate so the load_groq_api_key error message points
    # somewhere actionable.
    return candidates[0]


def main() -> int:
    config_path = user_config_path()
    dict_en_path = user_dictionary_path("en")
    dict_yue_path = user_dictionary_path("yue")
    log_path = user_log_path()
    env_path = _find_env_path()

    _configure_logging(log_path)
    log = logging.getLogger("wispr_clone")
    log.info("user data dir: %s", user_data_dir())

    try:
        api_key = load_groq_api_key(env_path)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    cfg = load_config(config_path)
    _ensure_dictionaries(dict_en_path, dict_yue_path)
    transcriber = Transcriber(api_key)

    tk_root = tk.Tk()
    tk_root.withdraw()  # we never show the root; HUD is a Toplevel.

    hud = HUD(tk_root)

    state_holder: dict = {
        "controller": None,
        "tray": None,
        "hotkey_en": None,
        "hotkey_yue": None,
        "shutdown_done": False,
    }

    def shutdown() -> None:
        if state_holder["shutdown_done"]:
            return
        state_holder["shutdown_done"] = True
        log.info("shutting down")
        for key in ("hotkey_en", "hotkey_yue"):
            listener = state_holder.get(key)
            if listener is not None:
                listener.stop()
        if state_holder["controller"] is not None:
            state_holder["controller"].shutdown()
        if state_holder["tray"] is not None:
            state_holder["tray"].stop()
        try:
            hud.destroy()
        except Exception:
            pass
        try:
            tk_root.quit()
            tk_root.destroy()
        except Exception:
            pass

    def on_state_change(s: State) -> None:
        if state_holder["tray"] is None:
            return
        mapping = {
            State.IDLE: "idle",
            State.RECORDING: "recording",
            State.TRANSCRIBING: "processing",
        }
        state_holder["tray"].set_state(mapping.get(s, "idle"))

    def on_error(msg: str) -> None:
        log.error(msg)
        if state_holder["tray"] is not None:
            state_holder["tray"].notify(msg)

    def on_configure_hotkey_en() -> None:
        log.info("Configure English hotkey clicked")
        tk_root.after(0, lambda: _open_hotkey_dialog(
            tk_root, cfg, config_path, state_holder["hotkey_en"],
            field="hotkey_english", title_suffix="English",
        ))

    def on_configure_hotkey_yue() -> None:
        log.info("Configure Cantonese hotkey clicked")
        tk_root.after(0, lambda: _open_hotkey_dialog(
            tk_root, cfg, config_path, state_holder["hotkey_yue"],
            field="hotkey_cantonese", title_suffix="Cantonese",
        ))

    def on_toggle_smart_cleanup() -> None:
        ctrl = state_holder["controller"]
        if ctrl is None:
            return
        new_value = not ctrl.smart_cleanup_enabled
        ctrl.set_smart_cleanup(new_value)
        log.info("smart cleanup -> %s", "ON" if new_value else "OFF")

    def is_smart_cleanup_enabled() -> bool:
        ctrl = state_holder["controller"]
        return bool(ctrl and ctrl.smart_cleanup_enabled)

    tray = Tray(
        dictionary_paths={"en": dict_en_path, "yue": dict_yue_path},
        on_configure_hotkey_en=on_configure_hotkey_en,
        on_configure_hotkey_yue=on_configure_hotkey_yue,
        on_toggle_smart_cleanup=on_toggle_smart_cleanup,
        is_smart_cleanup_enabled=is_smart_cleanup_enabled,
        on_quit=lambda: tk_root.after(0, shutdown),
    )
    state_holder["tray"] = tray

    controller = Controller(
        root=tk_root,
        config=cfg,
        config_path=config_path,
        transcriber=transcriber,
        hud=hud,
        on_state_change=on_state_change,
        on_error=on_error,
    )
    state_holder["controller"] = controller

    hotkey_en = HotkeyListener(
        combo=cfg.hotkey_english,
        on_press=controller.on_press_en,
        on_release=controller.on_release_en,
    )
    hotkey_yue = HotkeyListener(
        combo=cfg.hotkey_cantonese,
        on_press=controller.on_press_yue,
        on_release=controller.on_release_yue,
    )
    hotkey_en.start()
    hotkey_yue.start()
    state_holder["hotkey_en"] = hotkey_en
    state_holder["hotkey_yue"] = hotkey_yue

    tray.run_detached()
    log.info(
        "wispr-clone running. EN=%s YUE=%s. Smart cleanup=%s. Logs at %s. Right-click tray for menu.",
        cfg.hotkey_english,
        cfg.hotkey_cantonese,
        "ON" if cfg.enable_smart_cleanup else "OFF",
        log_path,
    )

    try:
        tk_root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        shutdown()
    # pystray's detached thread holds a hidden Win32 window even after
    # icon.stop(); force the process to exit so Quit actually quits.
    import os
    os._exit(0)


def _open_hotkey_dialog(
    tk_root: tk.Tk,
    cfg: Config,
    config_path: Path,
    hotkey_listener: HotkeyListener,
    field: str = "hotkey_english",
    title_suffix: str = "English",
) -> None:
    def _on_saved(new_combo: str) -> None:
        logging.getLogger("wispr_clone").info("%s hotkey changed to %s", title_suffix, new_combo)

    HotkeyDialog(
        parent=tk_root,
        cfg=cfg,
        config_path=config_path,
        hotkey_listener=hotkey_listener,
        on_saved=_on_saved,
        config_field=field,
        title_suffix=title_suffix,
    )


if __name__ == "__main__":
    sys.exit(main())
