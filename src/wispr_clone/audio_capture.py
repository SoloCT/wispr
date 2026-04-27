"""Microphone capture: streams int16 frames into an in-memory buffer.

Public API:
    AudioCapture(sample_rate, mic_device).start() / .stop() -> bytes (WAV)
    AudioCapture.get_current_level() -> float in [0.0, 1.0]
"""
from __future__ import annotations

import io
import threading
from collections import deque
from typing import Optional

import numpy as np
import sounddevice as sd
import soundfile as sf


# RMS reference for int16 normalization. Empirical: ~5000 RMS is "moderate
# speech" near a typical headset/desktop mic, which lands the meter near
# 50-70% during normal dictation.
LEVEL_RMS_REFERENCE = 5000.0

# How many recent frames to retain for the rolling level window.
# 50 ms @ 16 kHz = 800 samples; we keep ~10 callback chunks worth of int16.
LEVEL_WINDOW_SAMPLES = 800


class AudioCapture:
    def __init__(self, sample_rate: int = 16000, mic_device: str | int | None = None):
        self.sample_rate = sample_rate
        self.mic_device = mic_device if mic_device else None
        self._stream: Optional[sd.InputStream] = None
        self._frames: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._recent: deque[np.ndarray] = deque(maxlen=32)  # rolling level buffer
        # Set during stop(); read by the worker thread to compute Whisper cost.
        # Safe cross-thread: stop() runs on Tk thread; worker reads after stop().
        self.last_duration_seconds: float = 0.0

    def start(self) -> None:
        if self._stream is not None:
            return
        with self._lock:
            self._frames = []
            self._recent.clear()

        def _callback(indata, frames, time_info, status):
            # indata is float32 by default; we store as int16 to keep
            # the WAV encode + level math identical to plan spec.
            int16 = (indata[:, 0] * 32767).clip(-32768, 32767).astype(np.int16)
            with self._lock:
                self._frames.append(int16.copy())
                self._recent.append(int16.copy())

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            device=self.mic_device,
            callback=_callback,
        )
        self._stream.start()

    def stop(self) -> bytes:
        """Stop the stream and return the recorded audio as WAV bytes (mono int16)."""
        if self._stream is None:
            return b""
        self._stream.stop()
        self._stream.close()
        self._stream = None

        with self._lock:
            if not self._frames:
                self.last_duration_seconds = 0.0
                return b""
            audio = np.concatenate(self._frames)
            self._frames = []
            self._recent.clear()

        self.last_duration_seconds = audio.size / float(self.sample_rate)
        buf = io.BytesIO()
        sf.write(buf, audio, self.sample_rate, format="WAV", subtype="PCM_16")
        return buf.getvalue()

    def get_current_level(self) -> float:
        """RMS of the most recent ~50 ms of audio, normalized to 0.0–1.0."""
        with self._lock:
            if not self._recent:
                return 0.0
            recent = np.concatenate(list(self._recent))
        if recent.size == 0:
            return 0.0
        window = recent[-LEVEL_WINDOW_SAMPLES:].astype(np.float32)
        rms = float(np.sqrt(np.mean(window * window)))
        return max(0.0, min(1.0, rms / LEVEL_RMS_REFERENCE))

    def is_recording(self) -> bool:
        return self._stream is not None
