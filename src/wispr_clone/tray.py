"""System-tray icon. Runs detached on a background thread so the main thread
can own Tk. Generates icons at runtime via Pillow — no PNG asset files."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw
from pystray import Icon, Menu, MenuItem

from .paths import resource_path


COLOR_IDLE = (190, 190, 190)
COLOR_RECORDING = (229, 72, 72)
COLOR_PROCESSING = (230, 195, 73)

# If a PNG ships under assets/<state>.png it is preferred over the runtime
# Pillow drawing. Files are looked up via resource_path so this works under
# both dev and PyInstaller-bundled runs.
_ICON_FILES = {
    "idle": "assets/tray-idle.png",
    "recording": "assets/tray-recording.png",
    "processing": "assets/tray-processing.png",
}


def _make_icon(color: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), fill=color)
    # microphone glyph
    d.rectangle((26, 18, 38, 40), fill=(30, 30, 30))
    d.ellipse((26, 12, 38, 24), fill=(30, 30, 30))
    d.ellipse((26, 34, 38, 46), fill=(30, 30, 30))
    d.line((32, 46, 32, 54), fill=(30, 30, 30), width=2)
    d.line((22, 54, 42, 54), fill=(30, 30, 30), width=2)
    return img


def _load_icon(state: str, fallback_color: tuple[int, int, int]) -> Image.Image:
    path = resource_path(_ICON_FILES[state])
    if path.exists():
        try:
            return Image.open(path).convert("RGBA")
        except Exception:
            pass
    return _make_icon(fallback_color)


class Tray:
    def __init__(
        self,
        dictionary_paths: dict[str, Path],
        on_configure_hotkey_en: Callable[[], None],
        on_configure_hotkey_yue: Callable[[], None],
        on_toggle_smart_cleanup: Callable[[], None],
        is_smart_cleanup_enabled: Callable[[], bool],
        on_show_usage: Callable[[], None],
        on_quit: Callable[[], None],
    ):
        self._dictionary_paths = dictionary_paths
        self._on_configure_hotkey_en = on_configure_hotkey_en
        self._on_configure_hotkey_yue = on_configure_hotkey_yue
        self._on_toggle_smart_cleanup = on_toggle_smart_cleanup
        self._is_smart_cleanup_enabled = is_smart_cleanup_enabled
        self._on_show_usage = on_show_usage
        self._on_quit = on_quit

        self._icons = {
            "idle": _load_icon("idle", COLOR_IDLE),
            "recording": _load_icon("recording", COLOR_RECORDING),
            "processing": _load_icon("processing", COLOR_PROCESSING),
        }
        self._icon = Icon(
            "wispr-clone",
            self._icons["idle"],
            "wispr-clone (idle)",
            menu=Menu(
                MenuItem("wispr-clone", None, enabled=False),
                Menu.SEPARATOR,
                MenuItem("Configure English hotkey…", self._handle_configure_en),
                MenuItem("Configure Cantonese hotkey…", self._handle_configure_yue),
                MenuItem("Edit English dictionary…", self._handle_edit_dict_en),
                MenuItem("Edit Cantonese dictionary…", self._handle_edit_dict_yue),
                MenuItem("Edit English brands…", self._handle_edit_brands_en),
                Menu.SEPARATOR,
                MenuItem(
                    "Smart cleanup (auto-format lists)",
                    self._handle_toggle_smart_cleanup,
                    checked=lambda item: self._is_smart_cleanup_enabled(),
                ),
                MenuItem("Show usage…", self._handle_show_usage),
                Menu.SEPARATOR,
                MenuItem("Quit", self._handle_quit),
            ),
        )

    def run_detached(self) -> None:
        self._icon.run_detached()

    def stop(self) -> None:
        try:
            self._icon.stop()
        except Exception:
            pass

    def set_state(self, state: str) -> None:
        """state: 'idle' | 'recording' | 'processing'"""
        if state not in self._icons:
            return
        self._icon.icon = self._icons[state]
        self._icon.title = f"wispr-clone ({state})"

    def notify(self, message: str) -> None:
        try:
            self._icon.notify(message, "wispr-clone")
        except Exception:
            pass

    def _handle_configure_en(self, icon, item) -> None:
        self._on_configure_hotkey_en()

    def _handle_configure_yue(self, icon, item) -> None:
        self._on_configure_hotkey_yue()

    def _handle_edit_dict_en(self, icon, item) -> None:
        self._open_path(self._dictionary_paths.get("en"))

    def _handle_edit_dict_yue(self, icon, item) -> None:
        self._open_path(self._dictionary_paths.get("yue"))

    def _handle_edit_brands_en(self, icon, item) -> None:
        self._open_path(self._dictionary_paths.get("brands_en"))

    def _open_path(self, path: Path | None) -> None:
        if path is None:
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception:
            pass

    def _handle_toggle_smart_cleanup(self, icon, item) -> None:
        self._on_toggle_smart_cleanup()
        # pystray refreshes the checkmark on next menu open via the
        # `checked=` callable; explicit refresh just nudges the icon thread.
        try:
            self._icon.update_menu()
        except Exception:
            pass

    def _handle_show_usage(self, icon, item) -> None:
        self._on_show_usage()

    def _handle_quit(self, icon, item) -> None:
        self._on_quit()
