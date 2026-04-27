"""Clipboard-with-restore paste. Saves clipboard, sets transcript, sends Ctrl+V,
restores after a short delay so the user's original copy survives."""
from __future__ import annotations

import time

import keyboard
import pyperclip


# Time to wait after pyperclip.copy() before sending Ctrl+V. Windows
# clipboard writes are asynchronous; sending the paste keystroke too
# fast can paste stale clipboard content.
CLIPBOARD_PROPAGATION_DELAY_S = 0.05


def paste(text: str, restore_delay_ms: int = 150) -> None:
    if not text:
        return
    try:
        saved = pyperclip.paste()
    except Exception:
        saved = ""
    pyperclip.copy(text)
    time.sleep(CLIPBOARD_PROPAGATION_DELAY_S)
    keyboard.send("ctrl+v")
    # Block briefly so the destination app actually consumes the paste
    # before we mutate the clipboard again.
    time.sleep(restore_delay_ms / 1000.0)
    _safe_copy(saved)


def _safe_copy(text: str) -> None:
    try:
        pyperclip.copy(text)
    except Exception:
        pass
