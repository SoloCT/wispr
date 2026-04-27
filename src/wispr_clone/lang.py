"""Language identifiers used across the app.

We carry a small enum instead of bare strings so the rest of the codebase
isn't sprinkled with `"en"` / `"yue"` literals."""
from __future__ import annotations

from enum import Enum


class Language(str, Enum):
    EN = "en"
    YUE = "yue"


def whisper_code(lang: Language) -> str | None:
    """Whisper API language code, or None to auto-detect.

    English is auto-detect (None) on purpose: Whisper's `language="en"`
    parameter does not just *prefer* English — when the audio is actually
    in another language, it triggers translation-to-English behavior on
    the transcriptions endpoint. That's surprising for a dictation tool.
    Auto-detect leaves English audio as English while routing
    Cantonese-on-English-hotkey to Chinese output (so the wrong-hotkey
    case is visible instead of silently translated).

    Cantonese tries `yue` first because it preserves verbatim spoken
    Cantonese (書面粵語). If Groq's deployment rejects `yue`, the
    Transcriber falls back to `zh` automatically. With `zh` Whisper
    tends to translate Cantonese audio into Standard Written Chinese
    (書面語), which loses Cantonese particles like 嘅 / 咗 / 喺 — the
    `CANTONESE_PRIMING` sample fights that bias by setting register."""
    if lang is Language.YUE:
        return "yue"
    return None


def dict_filename(lang: Language) -> str:
    return f"dictionary-{lang.value}.txt"


def display_name(lang: Language) -> str:
    return {Language.EN: "English", Language.YUE: "Cantonese"}[lang]
