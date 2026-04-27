"""HUD smoke test: import + create + destroy without crashing.
No visual assertions. Skipped on systems without a display."""
from __future__ import annotations

import os
import sys

import pytest


@pytest.mark.skipif(
    sys.platform != "win32" and not os.environ.get("DISPLAY"),
    reason="No display available",
)
def test_hud_lifecycle():
    import tkinter as tk

    from wispr_clone.hud import HUD

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk not available")
    root.withdraw()
    try:
        hud = HUD(root)
        hud.show()
        hud.update_level(0.5)
        hud.set_state("transcribing")
        hud.update_level(0.8)  # ignored in transcribing state
        hud.hide()
        hud.destroy()
    finally:
        root.destroy()
