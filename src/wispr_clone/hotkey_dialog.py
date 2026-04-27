"""Tk dialog for capturing a new hotkey combo from a key press."""
from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from typing import Callable

import keyboard

from .config import Config, save_config
from .hotkey import HotkeyListener


_MODIFIER_ORDER = ["ctrl", "alt", "shift", "windows", "cmd"]


def _format_combo(keys: list[str]) -> str:
    """Order modifiers first, then the trigger key. Lowercase normalized."""
    seen: set[str] = set()
    mods: list[str] = []
    others: list[str] = []
    for k in keys:
        name = k.lower().replace("left ", "").replace("right ", "")
        if name in seen:
            continue
        seen.add(name)
        if name in _MODIFIER_ORDER:
            mods.append(name)
        else:
            others.append(name)
    mods.sort(key=lambda m: _MODIFIER_ORDER.index(m))
    return "+".join(mods + others)


def _capture_chord(timeout_idle_s: float = 0.05) -> str:
    """Block until the user presses one or more keys then releases them all.
    Returns the largest simultaneous combo seen during the hold."""
    held: set[str] = set()
    peak: list[str] = []
    done = threading.Event()

    def on_event(event) -> None:
        if event.event_type == "down":
            if event.name not in held:
                held.add(event.name)
                # Preserve insertion order so trigger key (last pressed) is last.
                if len(held) > len(peak):
                    peak.clear()
                    peak.extend(held)
        elif event.event_type == "up":
            held.discard(event.name)
            if peak and not held:
                done.set()

    hook = keyboard.hook(on_event, suppress=False)
    try:
        done.wait()
    finally:
        keyboard.unhook(hook)
    return _format_combo(peak)


class HotkeyDialog:
    def __init__(
        self,
        parent: tk.Tk,
        cfg: Config,
        config_path: Path,
        hotkey_listener: HotkeyListener,
        on_saved: Callable[[str], None] = lambda combo: None,
        config_field: str = "hotkey_english",
        title_suffix: str = "English",
    ):
        self._parent = parent
        self._cfg = cfg
        self._config_path = config_path
        self._hotkey_listener = hotkey_listener
        self._on_saved = on_saved
        self._config_field = config_field
        self._captured: str | None = None
        self._capture_thread: threading.Thread | None = None
        self._cancelled = False

        self._win = tk.Toplevel(parent)
        self._win.title(f"Configure {title_suffix} hotkey")
        # Center on primary monitor.
        sw = parent.winfo_screenwidth()
        sh = parent.winfo_screenheight()
        w, h = 360, 180
        self._win.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        self._win.resizable(False, False)
        self._win.protocol("WM_DELETE_WINDOW", self._cancel)
        # Withdrawn root → force the dialog visible and on top.
        self._win.attributes("-topmost", True)
        self._win.lift()
        self._win.focus_force()
        self._win.after(200, lambda: self._win.attributes("-topmost", False))

        tk.Label(
            self._win,
            text="Current hotkey:",
            font=("Segoe UI", 9),
        ).pack(pady=(14, 0))
        current_value = getattr(cfg, self._config_field, "")
        self._current_label = tk.Label(
            self._win,
            text=current_value,
            font=("Segoe UI", 11, "bold"),
        )
        self._current_label.pack()

        self._capture_label = tk.Label(
            self._win,
            text="Press the new key combination, then click Save.",
            font=("Segoe UI", 9),
            wraplength=320,
            justify="center",
        )
        self._capture_label.pack(pady=(14, 4))

        self._captured_var = tk.StringVar(value="(none yet)")
        tk.Label(
            self._win,
            textvariable=self._captured_var,
            font=("Segoe UI", 11, "bold"),
            fg="#1a6dd8",
        ).pack()

        button_frame = tk.Frame(self._win)
        button_frame.pack(side="bottom", pady=10)
        self._save_btn = tk.Button(
            button_frame, text="Save", width=10, command=self._save, state="disabled"
        )
        self._save_btn.pack(side="left", padx=4)
        tk.Button(button_frame, text="Cancel", width=10, command=self._cancel).pack(
            side="left", padx=4
        )

        # While the dialog is open, suspend the main hotkey listener so it
        # doesn't fire during capture.
        self._hotkey_listener.stop()
        self._start_capture_thread()

    def _start_capture_thread(self) -> None:
        def _capture() -> None:
            try:
                combo = _capture_chord()
            except Exception:
                combo = ""
            if self._cancelled:
                return
            if combo:
                self._captured = combo
                self._parent.after(0, lambda: self._on_captured(combo))
            else:
                self._parent.after(0, self._start_capture_thread)

        self._capture_thread = threading.Thread(target=_capture, daemon=True)
        self._capture_thread.start()

    def _on_captured(self, combo: str) -> None:
        self._captured_var.set(combo)
        self._save_btn.config(state="normal")
        self._capture_label.config(text="Captured. Click Save, or press another combo to redo.")
        self._start_capture_thread()

    def _save(self) -> None:
        if not self._captured:
            return
        new_combo = self._captured
        setattr(self._cfg, self._config_field, new_combo)
        save_config(self._config_path, self._cfg)
        try:
            self._hotkey_listener.set_combo(new_combo)
        except Exception:
            self._hotkey_listener.start()  # best-effort restore
        self._cancelled = True
        self._on_saved(new_combo)
        self._win.destroy()

    def _cancel(self) -> None:
        self._cancelled = True
        # Resume the original listener.
        try:
            self._hotkey_listener.start()
        except Exception:
            pass
        self._win.destroy()
