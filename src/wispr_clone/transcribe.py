"""Groq Whisper transcription client. Single-shot REST call per recording."""
from __future__ import annotations

import logging

from groq import Groq

MODEL = "whisper-large-v3-turbo"

# If Groq rejects an ISO-639-3 / non-639-1 code, retry once with the
# matching 639-1 code. The mapping is intentionally narrow — we only
# add fallbacks we've verified make sense.
_LANGUAGE_FALLBACKS = {
    "yue": "zh",
}

log = logging.getLogger(__name__)


class Transcriber:
    def __init__(self, api_key: str):
        self._client = Groq(api_key=api_key)
        # Sticky fallback: once we know `yue` is rejected by this Groq
        # deployment we stop trying it — saves ~1 round trip per take.
        self._sticky_fallback: dict[str, str] = {}

    @property
    def client(self) -> Groq:
        """Underlying Groq client. Reused by the smart-cleanup module so we
        don't re-auth a second SDK instance."""
        return self._client

    def transcribe(
        self,
        wav_bytes: bytes,
        prompt: str = "",
        language: str | None = None,
    ) -> str:
        if not wav_bytes:
            return ""

        effective = self._sticky_fallback.get(language or "", language)
        try:
            return self._call(wav_bytes, prompt, effective)
        except Exception as e:
            # Only retry on language-related rejection of the original code,
            # and only if we have a defined fallback for it. Anything else
            # propagates — the controller's exception handler will surface it.
            fallback = _LANGUAGE_FALLBACKS.get(language or "")
            if (
                fallback
                and effective == language  # haven't already fallen back
                and _looks_like_language_error(e)
            ):
                log.warning(
                    "Whisper rejected language=%s (%s); falling back to %s",
                    language, type(e).__name__, fallback,
                )
                self._sticky_fallback[language] = fallback
                return self._call(wav_bytes, prompt, fallback)
            raise

    def _call(self, wav_bytes: bytes, prompt: str, language: str | None) -> str:
        kwargs: dict = {
            "model": MODEL,
            "file": ("audio.wav", wav_bytes, "audio/wav"),
            "response_format": "text",
        }
        if prompt:
            kwargs["prompt"] = prompt
        if language:
            kwargs["language"] = language
        result = self._client.audio.transcriptions.create(**kwargs)
        # `response_format="text"` returns a plain string.
        text = result if isinstance(result, str) else getattr(result, "text", "")
        return text.strip()


def _looks_like_language_error(exc: Exception) -> bool:
    """Heuristic for 'Groq rejected our `language` parameter'. Groq's SDK
    surfaces 4xx body messages on `BadRequestError`; we match on substring
    rather than exception type to stay robust across SDK versions."""
    msg = str(exc).lower()
    return "language" in msg and ("invalid" in msg or "unsupported" in msg or "not supported" in msg or "bad request" in msg)
