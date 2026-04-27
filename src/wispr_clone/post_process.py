"""Filler-word stripping + light punctuation cleanup. Pure, fast, regex-only."""
from __future__ import annotations

import re

FILLER_RE = re.compile(r"\b(um+|uh+|erm+|er+|ah+)\b", re.IGNORECASE)


def strip_fillers(text: str) -> str:
    """Remove conservative filler words and tidy spacing/punctuation."""
    if not text:
        return text
    out = FILLER_RE.sub("", text)
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)   # space before punctuation
    out = re.sub(r",\s*,+", ",", out)            # collapse repeated commas
    out = re.sub(r"\s{2,}", " ", out)            # collapse internal spaces
    out = re.sub(r"^[\s,]+", "", out).strip()    # leading whitespace/commas
    if not out:
        return out
    return out[0].upper() + out[1:]
