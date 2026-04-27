"""Minimal recording HUD. Frameless, always-on-top, bottom-center of primary monitor.
Strict v1 scope: no cursor-follow, no multi-monitor logic, no extra animations."""
from __future__ import annotations

import tkinter as tk
from typing import Literal

WIDTH = 220
HEIGHT = 56
BOTTOM_MARGIN = 80
BG_COLOR = "#1a1a1a"
FG_COLOR = "#e6e6e6"
DOT_RECORDING = "#e54848"
DOT_TRANSCRIBING = "#e6c349"
METER_COLOR = "#4ca6ff"
METER_BG = "#2a2a2a"
ALPHA_VISIBLE = 0.92
FADE_STEPS = 8
FADE_INTERVAL_MS = 18  # ~150 ms over 8 steps


class HUD:
    def __init__(self, root: tk.Tk):
        self._root = root
        self._win = tk.Toplevel(root)
        self._win.withdraw()
        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)
        self._win.attributes("-alpha", ALPHA_VISIBLE)
        self._win.configure(bg=BG_COLOR)

        self._canvas = tk.Canvas(
            self._win,
            width=WIDTH,
            height=HEIGHT,
            bg=BG_COLOR,
            highlightthickness=0,
            bd=0,
        )
        self._canvas.pack(fill="both", expand=True)

        # Recording dot, left side, vertically centered.
        self._dot = self._canvas.create_oval(
            14, HEIGHT // 2 - 8, 30, HEIGHT // 2 + 8,
            fill=DOT_RECORDING,
            outline="",
        )

        # Status label (used in transcribing state).
        self._label = self._canvas.create_text(
            44, HEIGHT // 2,
            text="",
            anchor="w",
            fill=FG_COLOR,
            font=("Segoe UI", 10),
        )

        # Meter background bar.
        self._meter_x0 = 44
        self._meter_y0 = HEIGHT // 2 - 4
        self._meter_x1 = WIDTH - 14
        self._meter_y1 = HEIGHT // 2 + 4
        self._meter_bg = self._canvas.create_rectangle(
            self._meter_x0, self._meter_y0, self._meter_x1, self._meter_y1,
            fill=METER_BG,
            outline="",
        )
        self._meter_fill = self._canvas.create_rectangle(
            self._meter_x0, self._meter_y0, self._meter_x0, self._meter_y1,
            fill=METER_COLOR,
            outline="",
        )

        self._state: Literal["recording", "transcribing"] = "recording"
        self._fade_job: str | None = None

    def show(self) -> None:
        self._cancel_fade()
        self._win.attributes("-alpha", ALPHA_VISIBLE)
        self.set_state("recording")
        self._position()
        self._win.deiconify()
        self._win.lift()

    def set_state(self, state: Literal["recording", "transcribing"]) -> None:
        self._state = state
        if state == "recording":
            self._canvas.itemconfig(self._dot, fill=DOT_RECORDING)
            self._canvas.itemconfig(self._label, text="")
            self._canvas.itemconfig(self._meter_bg, state="normal")
            self._canvas.itemconfig(self._meter_fill, state="normal")
        else:  # transcribing
            self._canvas.itemconfig(self._dot, fill=DOT_TRANSCRIBING)
            self._canvas.itemconfig(self._label, text="Transcribing…")
            self._canvas.itemconfig(self._meter_bg, state="hidden")
            self._canvas.itemconfig(self._meter_fill, state="hidden")

    def update_level(self, level: float) -> None:
        if self._state != "recording":
            return
        level = max(0.0, min(1.0, float(level)))
        width = (self._meter_x1 - self._meter_x0) * level
        self._canvas.coords(
            self._meter_fill,
            self._meter_x0,
            self._meter_y0,
            self._meter_x0 + width,
            self._meter_y1,
        )

    def hide(self) -> None:
        self._fade_step(FADE_STEPS)

    def destroy(self) -> None:
        self._cancel_fade()
        try:
            self._win.destroy()
        except tk.TclError:
            pass

    def _position(self) -> None:
        self._win.update_idletasks()
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        x = (sw - WIDTH) // 2
        y = sh - HEIGHT - BOTTOM_MARGIN
        self._win.geometry(f"{WIDTH}x{HEIGHT}+{x}+{y}")

    def _fade_step(self, remaining: int) -> None:
        if remaining <= 0:
            try:
                self._win.attributes("-alpha", 0.0)
                self._win.withdraw()
            except tk.TclError:
                pass
            self._fade_job = None
            return
        alpha = ALPHA_VISIBLE * (remaining - 1) / FADE_STEPS
        try:
            self._win.attributes("-alpha", max(0.0, alpha))
        except tk.TclError:
            return
        self._fade_job = self._root.after(
            FADE_INTERVAL_MS,
            lambda: self._fade_step(remaining - 1),
        )

    def _cancel_fade(self) -> None:
        if self._fade_job is not None:
            try:
                self._root.after_cancel(self._fade_job)
            except tk.TclError:
                pass
            self._fade_job = None
