"""Filler-word stripping + light punctuation cleanup. Pure, fast, regex-only.

Language-aware: English uses word-boundary regex; Cantonese uses CJK-boundary
lookarounds (Python's `\\b` does not see CJK letter transitions) plus literal
substring removal for multi-character fillers."""
from __future__ import annotations

import re

FILLER_RE_EN = re.compile(r"\b(um+|uh+|erm+|er+|ah+)\b", re.IGNORECASE)

# Cantonese single-syllable interjections. We strip these globally rather
# than relying on word boundaries because Python's `\b` doesn't see
# transitions between CJK characters; Cantonese dictation rarely contains
# real words that consist solely of these characters, so the false-positive
# rate is low and matches the same conservative bar as the English filter.
FILLER_RE_YUE_SINGLE = re.compile(r"(嗯+|呃+|噉+)")
# Multi-char Cantonese fillers stripped as literal substrings — unambiguous
# fillers in dictation context.
FILLER_LITERALS_YUE = ("即係", "嗰個", "係呢個")


def strip_fillers(text: str, lang: str = "en") -> str:
    """Remove conservative filler words and tidy spacing/punctuation."""
    if not text:
        return text
    if lang == "yue":
        out = _strip_yue(text)
    else:
        out = FILLER_RE_EN.sub("", text)
    out = re.sub(r"\s+([,.;:!?，。；：！？])", r"\1", out)   # space before punctuation (incl. CJK)
    out = re.sub(r"[,，]\s*[,，]+", ",", out)               # collapse repeated commas
    out = re.sub(r"\s{2,}", " ", out)                      # collapse internal spaces
    out = re.sub(r"^[\s,，]+", "", out).strip()            # leading whitespace/commas
    if not out:
        return out
    if lang == "en":
        return out[0].upper() + out[1:]
    # Cantonese: leave casing alone (CJK has no case).
    return out


def _strip_yue(text: str) -> str:
    out = FILLER_RE_YUE_SINGLE.sub("", text)
    for lit in FILLER_LITERALS_YUE:
        out = out.replace(lit, "")
    return out
