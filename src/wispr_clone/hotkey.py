"""Global hotkey: hold-to-record semantics over the `keyboard` library."""
from __future__ import annotations

from typing import Callable, Optional

import keyboard


class HotkeyListener:
    """Registers a hotkey that fires `on_press` once on key-down and
    `on_release` once on key-up. Re-register via `set_combo()` to change."""

    def __init__(self, combo: str, on_press: Callable[[], None], on_release: Callable[[], None]):
        self._combo = combo
        self._on_press = on_press
        self._on_release = on_release
        self._held = False
        self._press_handle: Optional[object] = None
        self._release_handle: Optional[object] = None

    def start(self) -> None:
        self._press_handle = keyboard.on_press_key(
            self._main_key(), self._handle_down, suppress=False
        )
        self._release_handle = keyboard.on_release_key(
            self._main_key(), self._handle_up, suppress=False
        )

    def stop(self) -> None:
        if self._press_handle is not None:
            try:
                keyboard.unhook(self._press_handle)
            except (KeyError, ValueError):
                pass
            self._press_handle = None
        if self._release_handle is not None:
            try:
                keyboard.unhook(self._release_handle)
            except (KeyError, ValueError):
                pass
            self._release_handle = None
        self._held = False

    def set_combo(self, combo: str) -> None:
        self.stop()
        self._combo = combo
        self.start()

    def _main_key(self) -> str:
        # `keyboard.on_press_key` takes a single key name. For combos like
        # "ctrl+shift+space" we register on the last token (the trigger key)
        # and verify modifiers manually on the event.
        return self._combo.split("+")[-1].strip()

    def _modifiers_required(self) -> list[str]:
        parts = [p.strip() for p in self._combo.split("+")]
        return [p for p in parts[:-1] if p]

    def _modifiers_held(self) -> bool:
        for mod in self._modifiers_required():
            try:
                if not keyboard.is_pressed(mod):
                    return False
            except (ValueError, KeyError):
                # Unknown modifier name; treat as not held rather than crashing.
                return False
        return True

    def _handle_down(self, event) -> None:
        if self._held:
            return
        if not self._modifiers_held():
            return
        self._held = True
        try:
            self._on_press()
        except Exception:
            self._held = False
            raise

    def _handle_up(self, event) -> None:
        if not self._held:
            return
        self._held = False
        try:
            self._on_release()
        except Exception:
            pass
