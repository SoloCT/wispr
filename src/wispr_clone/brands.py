"""English brand-name canonicalization.

Two responsibilities, one module:

1. **Whisper biasing.** The brand list (bundled + user-override) is appended
   to the user dictionary so Whisper sees these terms in its `prompt`
   parameter. This biases recognition toward the right tokens.

2. **Post-transcription canonicalization.** Whisper often spells brand
   names correctly but capitalizes them wrong: ``openai`` instead of
   ``OpenAI``, ``next.js`` instead of ``Next.js``, ``Open AI`` (split)
   instead of ``OpenAI`` (joined). After ``strip_fillers`` we run a
   regex pass that normalizes each match to the canonical form.

The bundled list (``assets/brands-en.txt``) is curated to exclude common
English words (Apple, Amazon, Meta) — those false-positive on normal
prose. Users add their own ambiguous picks via the override file.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from .dictionary import load_terms
from .paths import resource_path

log = logging.getLogger(__name__)

BUNDLED_BRANDS_RELATIVE = "assets/brands-en.txt"


def _load_bundled() -> list[str]:
    """Read the bundled brand list. Returns [] if the asset is missing —
    the feature degrades to user-only entries rather than crashing."""
    path = resource_path(BUNDLED_BRANDS_RELATIVE)
    if not path.exists():
        log.warning("bundled brand list missing at %s", path)
        return []
    return load_terms(path)


def _load_user(path: Path) -> list[str]:
    return load_terms(path)


def combined_brands(user_path: Path) -> list[str]:
    """Bundled + user, deduped case-insensitively. User entries win on
    collision so they can override the bundled casing. Sorted by length
    descending so longer brands are matched first during canonicalization
    (prevents 'Open' clobbering 'OpenAI')."""
    bundled = _load_bundled()
    user = _load_user(user_path)
    seen: dict[str, str] = {}  # lower-key -> canonical
    # Insert bundled first, then user, so user overwrites.
    for term in bundled:
        seen[term.lower()] = term
    for term in user:
        seen[term.lower()] = term
    out = list(seen.values())
    out.sort(key=lambda s: (-len(s), s))
    return out


# ---------------------------------------------------------------------------
# Pattern building
# ---------------------------------------------------------------------------

def _kind(ch: str) -> str:
    if ch.isspace():
        return "space"
    if ch.isalpha():
        return "upper" if ch.isupper() else "lower"
    if ch.isdigit():
        return "digit"
    return "punct"


def _is_internal_boundary(prev: str, curr: str) -> bool:
    """True between two non-space chars where transcription may insert
    whitespace. Covers camelCase (lower→upper), letter↔digit, and any
    transition involving punctuation. Same-kind transitions (upper→upper,
    lower→lower, digit→digit) are NOT boundaries."""
    if prev == "space" or curr == "space":
        return False  # the space itself is the boundary
    if prev == "lower" and curr == "upper":
        return True
    if prev in ("lower", "upper") and curr == "digit":
        return True
    if prev == "digit" and curr in ("lower", "upper"):
        return True
    if prev == "punct" and curr in ("lower", "upper", "digit"):
        return True
    if prev in ("lower", "upper", "digit") and curr == "punct":
        return True
    return False


def _brand_to_pattern(canonical: str) -> re.Pattern[str]:
    """Compile a regex that matches `canonical` case-insensitively, with
    optional whitespace at every internal boundary (camelCase, letter↔
    digit, and any punctuation-adjacent transition). Internal punctuation
    is matched **optionally** so that Whisper's frequent dot-dropping
    (``next js`` instead of ``Next.js``) still canonicalizes. Anchored
    with `\\b` on alphanumeric edges."""
    if not canonical:
        return re.compile("(?!)")  # never matches
    parts: list[str] = []
    prev_kind: str | None = None
    for ch in canonical:
        kind = _kind(ch)
        if prev_kind is not None and _is_internal_boundary(prev_kind, kind):
            parts.append(r"\s*")
        if kind == "space":
            parts.append(r"\s*")
        elif kind == "punct":
            # Make internal punctuation optional. Whisper rarely
            # transcribes a literal "dot" in spoken English, so
            # `Node.js` ↔ `node js` and `DALL-E` ↔ `dalle` should both
            # canonicalize. False-positive risk is bounded by the
            # surrounding `\s*` and `\b` anchors.
            parts.append(re.escape(ch) + "?")
        else:
            parts.append(re.escape(ch))
        prev_kind = kind
    body = "".join(parts)
    # `\b` works between a word char and a non-word char. For brands that
    # start/end with alphanumerics (the common case), the standard \b is
    # exactly right. For brands that start/end with punct (e.g. ".NET"),
    # fall back to whitespace / start / end anchors.
    leading = r"\b" if canonical[0].isalnum() else r"(?:^|(?<=\s))"
    trailing = r"\b" if canonical[-1].isalnum() else r"(?:$|(?=\s))"
    return re.compile(leading + body + trailing, re.IGNORECASE)


def canonicalize_brands(text: str, brands: list[str]) -> str:
    """Replace each brand variant in `text` with its canonical form.
    `brands` should already be sorted longest-first (use
    `combined_brands`). Returns the original text on empty input or
    empty list."""
    if not text or not brands:
        return text
    out = text
    for canonical in brands:
        pattern = _brand_to_pattern(canonical)
        out = pattern.sub(canonical, out)
    return out
