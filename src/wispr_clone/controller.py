"""State machine: IDLE → RECORDING → TRANSCRIBING → PASTING → IDLE.

Hotkey callbacks call on_press / on_release. All HUD updates are marshaled
to the Tk thread via root.after(0, ...). Heavy work (HTTP, paste) runs on
a single-worker ThreadPoolExecutor so two fast presses do not race.
"""
from __future__ import annotations

import logging
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Optional

from .audio_capture import AudioCapture
from .config import Config, save_config
from .dictionary import CANTONESE_PRIMING, build_prompt, load_terms
from .hud import HUD
from .lang import Language, whisper_code
from .paste import paste
from .paths import user_dictionary_path, user_usage_log_path
from .post_process import strip_fillers
from .structure import apply_structure
from .transcribe import Transcriber
from .usage import record_event as usage_record_event

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
        transcriber: Transcriber,
        hud: HUD,
        on_state_change: Callable[[State], None] = lambda s: None,
        on_error: Callable[[str], None] = lambda msg: None,
    ):
        self._root = root
        self._config = config
        self._config_path = config_path
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
        self._active_language: Language = Language.EN
        self._smart_cleanup_enabled: bool = config.enable_smart_cleanup

    # ----- Hotkey callbacks (called from `keyboard` lib's listener thread) -----

    def on_press(self, language: Language = Language.EN) -> None:
        self._root.after(0, lambda: self._begin_recording(language))

    def on_release(self, language: Language = Language.EN) -> None:
        # Language passed for symmetry; the active language is whatever was
        # set on press, so we don't need to read it again here.
        self._root.after(0, self._end_recording)

    def on_press_en(self) -> None:
        self.on_press(Language.EN)

    def on_release_en(self) -> None:
        self.on_release(Language.EN)

    def on_press_yue(self) -> None:
        self.on_press(Language.YUE)

    def on_release_yue(self) -> None:
        self.on_release(Language.YUE)

    # ----- Smart-cleanup runtime toggle -----

    @property
    def smart_cleanup_enabled(self) -> bool:
        return self._smart_cleanup_enabled

    def set_smart_cleanup(self, enabled: bool) -> None:
        self._smart_cleanup_enabled = bool(enabled)
        self._config.enable_smart_cleanup = self._smart_cleanup_enabled
        try:
            save_config(self._config_path, self._config)
        except Exception:
            log.exception("failed to persist smart_cleanup toggle")

    # ----- Tk-thread methods -----

    def _begin_recording(self, language: Language = Language.EN) -> None:
        with self._lock:
            if self._state is not State.IDLE:
                return
            self._state = State.RECORDING
            self._active_language = language
        log.info("press: language=%s", language.value)
        try:
            self._capture.start()
        except Exception as e:
            log.exception("audio start failed")
            self._on_error(f"Mic error: {e}")
            self._state = State.IDLE
            return
        self._hud.show(language=language.value)
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

        self._hud.set_state("transcribing", language=self._active_language.value)
        self._on_state_change(State.TRANSCRIBING)
        self._executor.submit(self._do_transcribe_and_paste, wav_bytes, self._active_language)

    # ----- Worker-thread method -----

    def _do_transcribe_and_paste(self, wav_bytes: bytes, language: Language) -> None:
        # Snapshot audio duration here. _capture.stop() ran on the Tk thread
        # in _end_recording before submitting this worker task, so the value
        # is populated and stable until the next start().
        audio_seconds = self._capture.last_duration_seconds
        text = ""
        error_msg: Optional[str] = None
        usage_sink: dict = {}
        # Per-stage timings (ms). Logged at end so we have a single line to grep.
        t_total = time.perf_counter()
        ms_whisper = 0.0
        ms_fillers = 0.0
        ms_cleanup = 0.0
        ms_paste = 0.0
        try:
            try:
                dict_path = user_dictionary_path(language.value)
                terms = load_terms(dict_path)
                prefix = CANTONESE_PRIMING if language is Language.YUE else ""
                prompt = build_prompt(terms, prefix=prefix)
                whisper_lang = whisper_code(language)
                log.info(
                    "transcribe: lang=%s whisper_lang=%s dict=%s prompt_len=%d audio_s=%.2f",
                    language.value, whisper_lang or "auto", dict_path.name, len(prompt), audio_seconds,
                )
                t = time.perf_counter()
                text = self._transcriber.transcribe(
                    wav_bytes,
                    prompt=prompt,
                    language=whisper_lang,
                )
                ms_whisper = (time.perf_counter() - t) * 1000.0
                log.info("transcribe result (len=%d): %r", len(text), text[:120])
                t = time.perf_counter()
                text = strip_fillers(text, lang=language.value)
                ms_fillers = (time.perf_counter() - t) * 1000.0
                if self._smart_cleanup_enabled:
                    t = time.perf_counter()
                    text = apply_structure(
                        text,
                        lang=language.value,
                        client=self._transcriber.client,
                        model=self._config.cleanup_model,
                        timeout_ms=self._config.cleanup_timeout_ms,
                        usage_sink=usage_sink,
                    )
                    ms_cleanup = (time.perf_counter() - t) * 1000.0
            except Exception as e:
                log.exception("transcription failed")
                error_msg = f"Transcription failed: {e}"
                msg = error_msg
                self._root.after(0, lambda: self._on_error(msg))
                self._root.after(0, self._reset_to_idle)
                return

            if not text:
                self._root.after(0, self._reset_to_idle)
                return

            try:
                t = time.perf_counter()
                paste(text, restore_delay_ms=self._config.clipboard_restore_delay_ms)
                ms_paste = (time.perf_counter() - t) * 1000.0
            except Exception as e:
                log.exception("paste failed")
                error_msg = f"Paste failed: {e}"
                msg = error_msg
                self._root.after(0, lambda: self._on_error(msg))

            self._root.after(0, self._reset_to_idle)
        finally:
            ms_total = (time.perf_counter() - t_total) * 1000.0
            log.info(
                "timing ms: total=%.0f whisper=%.0f fillers=%.1f cleanup=%.0f paste=%.0f "
                "(audio_s=%.2f cleanup_used=%s)",
                ms_total, ms_whisper, ms_fillers, ms_cleanup, ms_paste,
                audio_seconds, bool(usage_sink.get("called", False)),
            )
            self._record_usage(language, audio_seconds, text, usage_sink, error_msg)

    def _record_usage(
        self,
        language: Language,
        audio_seconds: float,
        text: str,
        usage_sink: dict,
        error_msg: Optional[str],
    ) -> None:
        if not self._config.enable_usage_tracking:
            return
        try:
            usage_record_event(
                user_usage_log_path(),
                language=language.value,
                audio_seconds=audio_seconds,
                transcript_chars=len(text or ""),
                cleanup_used=bool(usage_sink.get("called", False)),
                cleanup_input_tokens=int(usage_sink.get("input_tokens", 0)),
                cleanup_output_tokens=int(usage_sink.get("output_tokens", 0)),
                error=error_msg,
            )
        except Exception:
            log.exception("usage tracking failed")

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
