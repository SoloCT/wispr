"""State machine: IDLE → RECORDING → TRANSCRIBING → PASTING → IDLE.

Hotkey callbacks call on_press / on_release. All HUD updates are marshaled
to the Tk thread via root.after(0, ...). Heavy work (HTTP, paste) runs on
a single-worker ThreadPoolExecutor so two fast presses do not race.
"""
from __future__ import annotations

import logging
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Optional

from .audio_capture import AudioCapture
from .config import Config
from .dictionary import build_prompt, load_terms
from .hud import HUD
from .paste import paste
from .post_process import strip_fillers
from .transcribe import Transcriber

log = logging.getLogger(__name__)

LEVEL_POLL_MS = 50


class State(Enum):
    IDLE = auto()
    RECORDING = auto()
    TRANSCRIBING = auto()


class Controller:
    def __init__(
        self,
        root: tk.Tk,
        config: Config,
        config_path: Path,
        dictionary_path: Path,
        transcriber: Transcriber,
        hud: HUD,
        on_state_change: Callable[[State], None] = lambda s: None,
        on_error: Callable[[str], None] = lambda msg: None,
    ):
        self._root = root
        self._config = config
        self._config_path = config_path
        self._dictionary_path = dictionary_path
        self._transcriber = transcriber
        self._hud = hud
        self._on_state_change = on_state_change
        self._on_error = on_error

        self._capture = AudioCapture(
            sample_rate=config.sample_rate,
            mic_device=config.mic_device or None,
        )
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._state = State.IDLE
        self._lock = threading.Lock()
        self._level_poll_job: Optional[str] = None
        self._max_record_job: Optional[str] = None

    # ----- Hotkey callbacks (called from `keyboard` lib's listener thread) -----

    def on_press(self) -> None:
        self._root.after(0, self._begin_recording)

    def on_release(self) -> None:
        self._root.after(0, self._end_recording)

    # ----- Tk-thread methods -----

    def _begin_recording(self) -> None:
        with self._lock:
            if self._state is not State.IDLE:
                return
            self._state = State.RECORDING
        try:
            self._capture.start()
        except Exception as e:
            log.exception("audio start failed")
            self._on_error(f"Mic error: {e}")
            self._state = State.IDLE
            return
        self._hud.show()
        self._on_state_change(State.RECORDING)
        self._schedule_level_poll()
        self._max_record_job = self._root.after(
            self._config.max_recording_seconds * 1000,
            self._auto_stop_recording,
        )

    def _auto_stop_recording(self) -> None:
        if self._state is State.RECORDING:
            log.info("max_recording_seconds reached, auto-stopping")
            self._end_recording()

    def _end_recording(self) -> None:
        with self._lock:
            if self._state is not State.RECORDING:
                return
            self._state = State.TRANSCRIBING
        self._cancel_jobs()
        try:
            wav_bytes = self._capture.stop()
        except Exception as e:
            log.exception("audio stop failed")
            self._on_error(f"Mic error: {e}")
            self._reset_to_idle()
            return

        if not wav_bytes:
            self._reset_to_idle()
            return

        self._hud.set_state("transcribing")
        self._on_state_change(State.TRANSCRIBING)
        self._executor.submit(self._do_transcribe_and_paste, wav_bytes)

    # ----- Worker-thread method -----

    def _do_transcribe_and_paste(self, wav_bytes: bytes) -> None:
        try:
            terms = load_terms(self._dictionary_path)
            prompt = build_prompt(terms)
            text = self._transcriber.transcribe(wav_bytes, prompt=prompt)
            text = strip_fillers(text)
        except Exception as e:
            log.exception("transcription failed")
            self._root.after(0, lambda: self._on_error(f"Transcription failed: {e}"))
            self._root.after(0, self._reset_to_idle)
            return

        if not text:
            self._root.after(0, self._reset_to_idle)
            return

        try:
            paste(text, restore_delay_ms=self._config.clipboard_restore_delay_ms)
        except Exception as e:
            log.exception("paste failed")
            self._root.after(0, lambda: self._on_error(f"Paste failed: {e}"))

        self._root.after(0, self._reset_to_idle)

    # ----- Tk-thread helpers -----

    def _reset_to_idle(self) -> None:
        with self._lock:
            self._state = State.IDLE
        self._hud.hide()
        self._on_state_change(State.IDLE)

    def _schedule_level_poll(self) -> None:
        def tick() -> None:
            if self._state is not State.RECORDING:
                self._level_poll_job = None
                return
            try:
                level = self._capture.get_current_level()
            except Exception:
                level = 0.0
            self._hud.update_level(level)
            self._level_poll_job = self._root.after(LEVEL_POLL_MS, tick)

        self._level_poll_job = self._root.after(LEVEL_POLL_MS, tick)

    def _cancel_jobs(self) -> None:
        if self._level_poll_job is not None:
            try:
                self._root.after_cancel(self._level_poll_job)
            except tk.TclError:
                pass
            self._level_poll_job = None
        if self._max_record_job is not None:
            try:
                self._root.after_cancel(self._max_record_job)
            except tk.TclError:
                pass
            self._max_record_job = None

    def shutdown(self) -> None:
        self._cancel_jobs()
        try:
            self._capture.stop()
        except Exception:
            pass
        self._executor.shutdown(wait=False, cancel_futures=True)

    @property
    def state(self) -> State:
        return self._state
