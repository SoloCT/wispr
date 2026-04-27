"""Tk dialog showing per-dictation usage totals (count, audio minutes,
estimated USD cost) for today / last 7 days / all-time, plus per-language
breakdown. Reads `usage.jsonl` on open."""
from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from . import usage


def _fmt_audio(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes = seconds / 60.0
    if minutes < 60:
        return f"{minutes:.1f} min"
    return f"{minutes / 60.0:.1f} hr"


def _fmt_cost(cost_usd: float) -> str:
    # Sub-cent gets 4 decimals; cent-or-more gets 2.
    if cost_usd < 0.01:
        return f"${cost_usd:.4f}"
    return f"${cost_usd:.2f}"


def _fmt_bucket(bucket: dict) -> str:
    if bucket["count"] == 0:
        return "no dictations"
    return (
        f"{bucket['count']} dictations · "
        f"{_fmt_audio(bucket['audio_s'])} · "
        f"{_fmt_cost(bucket['cost_usd'])}"
    )


_LANG_LABEL = {"en": "English", "yue": "Cantonese"}


class UsageDialog:
    def __init__(self, parent: tk.Tk, usage_path: Path):
        self._parent = parent
        self._usage_path = usage_path

        self._win = tk.Toplevel(parent)
        self._win.title("wispr-clone usage")
        sw = parent.winfo_screenwidth()
        sh = parent.winfo_screenheight()
        w, h = 420, 320
        self._win.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        self._win.resizable(False, False)
        self._win.attributes("-topmost", True)
        self._win.lift()
        self._win.focus_force()
        self._win.after(200, lambda: self._win.attributes("-topmost", False))

        self._body = tk.Frame(self._win, padx=16, pady=14)
        self._body.pack(fill="both", expand=True)
        self._render()

        button_frame = tk.Frame(self._win)
        button_frame.pack(side="bottom", pady=10)
        tk.Button(button_frame, text="Open log file", width=14, command=self._open_log).pack(
            side="left", padx=4
        )
        tk.Button(button_frame, text="Reset", width=10, command=self._reset).pack(
            side="left", padx=4
        )
        tk.Button(button_frame, text="Close", width=10, command=self._win.destroy).pack(
            side="left", padx=4
        )

    def _render(self) -> None:
        for child in self._body.winfo_children():
            child.destroy()

        summary = usage.summarize(self._usage_path)

        tk.Label(
            self._body,
            text="wispr-clone usage",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w")
        tk.Label(self._body, text=" ").pack(anchor="w")  # spacer

        rows = [
            ("Today", summary["today"]),
            ("Last 7 days", summary["last_7d"]),
            ("All time", summary["all_time"]),
        ]
        for label, bucket in rows:
            row = tk.Frame(self._body)
            row.pack(anchor="w", fill="x")
            tk.Label(row, text=label, font=("Segoe UI", 9, "bold"), width=12, anchor="w").pack(side="left")
            tk.Label(row, text=_fmt_bucket(bucket), font=("Segoe UI", 9)).pack(side="left")

        if summary["by_language"]:
            tk.Label(self._body, text=" ").pack(anchor="w")
            tk.Label(
                self._body, text="By language", font=("Segoe UI", 9, "bold")
            ).pack(anchor="w")
            for lang_code, bucket in sorted(summary["by_language"].items()):
                row = tk.Frame(self._body)
                row.pack(anchor="w", fill="x")
                label = _LANG_LABEL.get(lang_code, lang_code)
                tk.Label(row, text=f"  {label}", width=12, anchor="w", font=("Segoe UI", 9)).pack(side="left")
                tk.Label(row, text=_fmt_bucket(bucket), font=("Segoe UI", 9)).pack(side="left")

        if summary["error_count"]:
            tk.Label(
                self._body,
                text=f"\n{summary['error_count']} error(s) recorded",
                font=("Segoe UI", 8),
                fg="#a04040",
            ).pack(anchor="w")

        tk.Label(
            self._body,
            text="Costs are estimates based on Groq's published rates.",
            font=("Segoe UI", 8),
            fg="#666",
        ).pack(anchor="w", pady=(10, 0))

    def _open_log(self) -> None:
        if not self._usage_path.exists():
            messagebox.showinfo("wispr-clone", "No usage log yet.", parent=self._win)
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(self._usage_path))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(self._usage_path)])
        except Exception:
            pass

    def _reset(self) -> None:
        confirm = messagebox.askyesno(
            "Reset usage log",
            "Delete all recorded usage history? This cannot be undone.",
            parent=self._win,
        )
        if not confirm:
            return
        usage.clear(self._usage_path)
        self._render()
