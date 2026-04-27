"""Groq Whisper transcription client. Single-shot REST call per recording."""
from __future__ import annotations

from groq import Groq

MODEL = "whisper-large-v3-turbo"


class Transcriber:
    def __init__(self, api_key: str):
        self._client = Groq(api_key=api_key)

    def transcribe(self, wav_bytes: bytes, prompt: str = "") -> str:
        if not wav_bytes:
            return ""
        kwargs: dict = {
            "model": MODEL,
            "file": ("audio.wav", wav_bytes, "audio/wav"),
            "response_format": "text",
        }
        if prompt:
            kwargs["prompt"] = prompt
        result = self._client.audio.transcriptions.create(**kwargs)
        # `response_format="text"` returns a plain string.
        text = result if isinstance(result, str) else getattr(result, "text", "")
        return text.strip()
