"""Smart cleanup of dictated text into Markdown lists.

Pipeline contract:
    apply_structure(text, lang, *, client, model, timeout_ms) -> str

The pipeline tries cheap deterministic splitters first, then falls back to
a small LLM only when the heuristic gate suggests structuring AND no
deterministic splitter matched. On any rejection / failure, the original
text is returned unchanged.

    1. _split_ordinal_list — first/second/third (or 第一/第二/第三),
       drops verbal ordinals + lead-ins, emits a numbered list.
    2. _split_comma_list — 3+ short comma-separated items, emits bullets.
    3. LLM cleanup — for messier listing-shaped text the deterministic
       splitters decline. System prompt permits dropping ordinal /
       lead-in tokens; guardrails exclude those tokens from the
       missing-token count.

The module imports nothing from controller / main; it accepts an injected
Groq client so tests can mock the call cleanly."""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

log = logging.getLogger(__name__)

# Length gate.
MIN_LEN = 15
MAX_LEN = 2000

# Listing-cue patterns.
_EN_ORDINAL_WORDS = ("first", "second", "third", "fourth", "fifth")
_EN_NUMBER_WORDS = ("one", "two", "three", "four", "five")
_YUE_ORDINALS = ("第一", "第二", "第三", "第四", "第五")
_YUE_NUMBERS = ("一", "二", "三", "四", "五")
_TRIGGER_PHRASES_EN = (
    "as a list", "bullet points", "in bullets", "as bullets",
    "numbered list", "list out", "list them",
)
_TRIGGER_PHRASES_YUE = ("列出嚟", "分點", "要點", "列出來", "列點")

_CJK_CHAR = re.compile(r"[一-鿿]")
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[一-鿿]")
_LIST_MARKER_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+", re.MULTILINE)


# ---------------------------------------------------------------------------
# Heuristic gate (LLM path only)
# ---------------------------------------------------------------------------

def _ordinal_run(text_lower: str, words: tuple[str, ...]) -> bool:
    """True if the first three ordinals appear in text in order."""
    pos = 0
    for w in words[:3]:
        found = text_lower.find(w, pos)
        if found < 0:
            return False
        pos = found + len(w)
    return True


def _short_clause_count(text: str) -> int:
    parts = re.split(r"[,，、]", text)
    return sum(1 for p in parts if 1 <= len(p.strip()) <= 40)


def _has_trigger(text_lower: str, phrases: tuple[str, ...]) -> bool:
    return any(p in text_lower for p in phrases)


def should_structure(text: str, lang: str = "en") -> bool:
    """Heuristic gate used for the LLM-fallback path. Deterministic
    splitters bypass this gate — they have their own match conditions."""
    if not text:
        return False
    if len(text) < MIN_LEN or len(text) > MAX_LEN:
        return False

    lower = text.lower()
    score = 0

    if lang == "yue":
        if all(o in text for o in _YUE_ORDINALS[:3]) or all(n in text for n in _YUE_NUMBERS[:3]):
            score += 1
        if _has_trigger(text, _TRIGGER_PHRASES_YUE):
            score += 1
    else:
        if _ordinal_run(lower, _EN_ORDINAL_WORDS) or _ordinal_run(lower, _EN_NUMBER_WORDS):
            score += 1
        if _has_trigger(lower, _TRIGGER_PHRASES_EN):
            score += 1

    if _short_clause_count(text) >= 3:
        score += 1

    return score >= 2


# ---------------------------------------------------------------------------
# Deterministic ordinal splitter
# ---------------------------------------------------------------------------

# Word-boundary ordinal markers (case-insensitive).
_EN_ORDINAL_WORD_RES = [re.compile(rf"\b{w}\b", re.IGNORECASE) for w in _EN_ORDINAL_WORDS]

# Count-words: the first ("one") can sit anywhere word-boundaried; the
# rest must be clause-anchored (after a comma / period / semicolon /
# colon, or start-of-text), so "one of the things to do is two-fold"
# does not false-positive.
_EN_COUNT_FIRST_RE = re.compile(rf"\b{_EN_NUMBER_WORDS[0]}\b", re.IGNORECASE)
_EN_COUNT_REST_RES = [
    re.compile(rf"(?:(?<=^)|(?<=[,.;:]))\s*\b{w}\b", re.IGNORECASE)
    for w in _EN_NUMBER_WORDS[1:]
]

_YUE_ORDINAL_RES = [re.compile(re.escape(o)) for o in _YUE_ORDINALS]

# Two separate lead-in stripping regexes so we can peel off a pronoun and
# then peel off an aux verb in successive iterations. Combining them into
# one pattern misses "you need garlic" (where the pronoun is present but
# the verb has no trailing "to").
_LEAD_PRONOUN_RE = re.compile(r"^\s*(?:you|we|i|they|it)\b\s*", re.IGNORECASE)
_LEAD_VERB_RE = re.compile(
    r"^\s*"
    # modal/aux verbs that signal "lead-in":
    r"(?:need(?:s)?(?:\s+to)?|have(?:\s+to)?|has(?:\s+to)?|"
    r"should|can|must|gotta|"
    r"are|is|was|were|will|would|"
    # particles + connectors:
    r"then|and|so|also|to|the)"
    # NOTE: do/does/did are intentionally NOT lead-ins — they often carry
    # the action ("first do the build"). Stripping them would erase content.
    r"\b\s*",
    re.IGNORECASE,
)

# Trailing connector words to trim from the intro before colon-normalizing.
_INTRO_TAIL_CONNECTOR_RE = re.compile(
    r"(?:^|\s)(so|now|then|well|ok|okay|alright)\s*[.,;:!?]*\s*$",
    re.IGNORECASE,
)


def _strip_intro_connectors(intro: str) -> str:
    """Trim trailing 'So' / 'Now' / 'Alright' connectors and normalize the
    intro to end with a colon. Returns '' if the intro is empty after trim."""
    out = intro.strip()
    if not out:
        return ""
    # Strip up to two trailing connector words (handles "well so").
    for _ in range(2):
        m = _INTRO_TAIL_CONNECTOR_RE.search(out)
        if not m:
            break
        out = out[: m.start()].rstrip()
    if not out:
        return ""
    # Replace trailing sentence punctuation with a colon; if no terminator,
    # append one for grammar.
    if out[-1] in ".?!":
        out = out[:-1] + ":"
    elif out[-1] not in ":;,":
        out = out + ":"
    return out


def _clean_segment(seg: str) -> str:
    """Strip leading pronouns + aux verbs + trailing punctuation."""
    out = seg
    for _ in range(8):
        new = _LEAD_PRONOUN_RE.sub("", out, count=1)
        new = _LEAD_VERB_RE.sub("", new, count=1)
        if new == out:
            break
        out = new
    out = out.strip()
    out = out.strip(",.;:!?，。；：！？ \t\r\n")
    return out


def _maybe_lowercase_first(seg: str) -> str:
    """Lowercase the leading letter only when the segment is a short
    noun-shaped fragment. Sentence-shaped items keep their casing."""
    if not seg or len(seg) >= 30:
        return seg
    if seg[0].isupper() and seg[0].isascii():
        # Only flip if no internal sentence punctuation suggests it's a clause.
        if not re.search(r"[.;:!?]", seg):
            return seg[0].lower() + seg[1:]
    return seg


def _find_ordinal_positions(text: str, lang: str) -> Optional[list[tuple[int, int]]]:
    """Return list of (start, end) positions of ordinal markers in
    left-to-right order, or None if 3+ markers are not found in
    canonical sequence."""
    if lang == "yue":
        positions: list[tuple[int, int]] = []
        cursor = 0
        for pat in _YUE_ORDINAL_RES:
            m = pat.search(text, cursor)
            if not m:
                break
            positions.append((m.start(), m.end()))
            cursor = m.end()
        return positions if len(positions) >= 3 else None

    # English path #1: first/second/third (… fourth fifth) — all word-bounded.
    positions = []
    cursor = 0
    for pat in _EN_ORDINAL_WORD_RES:
        m = pat.search(text, cursor)
        if not m:
            break
        if positions and m.start() - positions[-1][1] < 3:
            positions = []
            break
        positions.append((m.start(), m.end()))
        cursor = m.end()
    if len(positions) >= 3:
        return positions

    # English path #2: one/two/three (… four five). The first marker can
    # sit anywhere; the rest must be clause-anchored.
    positions = []
    cursor = 0
    m = _EN_COUNT_FIRST_RE.search(text)
    if not m:
        return None
    positions.append((m.start(), m.end()))
    cursor = m.end()
    for pat in _EN_COUNT_REST_RES:
        m = pat.search(text, cursor)
        if not m:
            break
        if m.start() - positions[-1][1] < 3:
            positions = []
            break
        positions.append((m.start(), m.end()))
        cursor = m.end()
    if len(positions) >= 3:
        return positions
    return None


def _split_ordinal_list(text: str, lang: str) -> Optional[str]:
    """Deterministic ordinal-list reformatter.

    Returns a Markdown numbered list (with optional intro sentence) when
    the text contains 3+ canonical ordinal markers, else None. No
    MIN_LEN gate — the 3-marker requirement is the gate."""
    if not text:
        return None
    positions = _find_ordinal_positions(text, lang)
    if positions is None:
        return None

    # Intro = text before the first ordinal marker.
    intro = _strip_intro_connectors(text[: positions[0][0]])

    # Carve out each item: from the END of one marker to the START of the
    # next marker, or to end-of-text for the last item.
    items: list[str] = []
    for i, (_start, end) in enumerate(positions):
        item_end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        raw_segment = text[end:item_end]
        segment = _clean_segment(raw_segment)
        segment = _maybe_lowercase_first(segment)
        if segment:
            items.append(segment)

    if len(items) < 3:
        return None

    numbered = [f"{i + 1}. {seg}" for i, seg in enumerate(items)]
    if intro:
        return intro + "\n" + "\n".join(numbered)
    return "\n".join(numbered)


# ---------------------------------------------------------------------------
# Deterministic comma-only splitter
# ---------------------------------------------------------------------------

_COMMA_SHORT_ITEM_MAX = 15


def _split_comma_list(text: str, lang: str) -> Optional[str]:
    """3+ comma-separated items, every part ≤ 15 chars after strip and
    trailing punctuation removal. Returns a bulleted Markdown list or
    None. No MIN_LEN gate — the all-items-short rule is the gate."""
    if not text:
        return None
    raw_parts = re.split(r"[,，、]", text)
    items: list[str] = []
    for raw in raw_parts:
        cleaned = raw.strip().strip(".!?。！？ \t\r\n")
        if not cleaned:
            continue
        if len(cleaned) > _COMMA_SHORT_ITEM_MAX:
            return None  # Long item disqualifies — let LLM handle.
        items.append(cleaned)
    if len(items) < 3:
        return None
    return "\n".join(f"- {it}" for it in items)


# ---------------------------------------------------------------------------
# LLM-fallback validation
# ---------------------------------------------------------------------------

# Tokens the LLM is allowed to drop without penalty. Lower-cased.
_DROPPABLE_TOKENS: frozenset[str] = frozenset({
    # Ordinals and number-words.
    "first", "second", "third", "fourth", "fifth",
    "one", "two", "three", "four", "five",
    # Pronoun + aux lead-in helpers (matches _LEAD_PRONOUN_RE +
    # _LEAD_VERB_RE; do/does/did intentionally excluded).
    "you", "i", "we", "they", "it",
    "to", "the",
    "need", "needs", "have", "has", "should", "can", "must",
    "is", "are", "was", "were", "will", "would",
    "then", "and", "so", "also", "now",
})


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text)}


def _strip_for_compare(text: str) -> str:
    """Remove list markers and whitespace before length comparison."""
    no_markers = _LIST_MARKER_RE.sub("", text)
    return re.sub(r"\s+", "", no_markers)


def _validate_cleaned(raw: str, cleaned: str) -> bool:
    """Reject obvious hallucinations. False = throw away `cleaned`.

    The token-set check ignores well-known droppable tokens (verbal
    ordinals, lead-in helpers). Cantonese ordinals 第一/第二/etc. don't
    tokenize as a single token under _TOKEN_RE (each CJK char is its own
    token), so 第/一/二/三/四/五 are handled by including them in the
    droppable set."""
    if not cleaned:
        return False
    raw_stripped = _strip_for_compare(raw)
    cleaned_stripped = _strip_for_compare(cleaned)
    if not raw_stripped or not cleaned_stripped:
        return False

    ratio = len(cleaned_stripped) / len(raw_stripped)
    if ratio < 0.7 or ratio > 1.3:
        return False

    raw_tokens = _tokens(raw)
    cleaned_tokens = _tokens(cleaned)
    droppable = _DROPPABLE_TOKENS | {"第", "一", "二", "三", "四", "五"}
    raw_significant = raw_tokens - droppable
    if not raw_significant:
        return True
    missing = raw_significant - cleaned_tokens
    if len(missing) / len(raw_significant) > 0.15:
        return False
    return True


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You reformat dictated text into Markdown lists when the speaker is "
    "clearly enumerating items. You MAY drop redundant ordinal words "
    "('first', 'second', 'third', 'one', 'two', 'three', '第一', '第二', "
    "'第三') and short verbal lead-ins ('you need to', 'we have to', "
    "'it's', 'is', 'are') so the list reads cleanly. Preserve every "
    "CONTENT word: nouns, verbs, adjectives, names. Do not paraphrase, "
    "summarize, translate, or fix grammar. Output numbered lists "
    "(1. 2. 3.) when the speaker said ordinals; bullet lists ('- ') when "
    "they only used commas. If the text is not actually a list, return it "
    "unchanged. Output only the reformatted text — no explanation."
)


def structure_text(
    text: str,
    *,
    client: Any,
    model: str = "llama-3.1-8b-instant",
    timeout_s: float = 3.0,
) -> Optional[str]:
    """Run a single chat-completion pass. Returns the cleaned text on
    success (after guardrails), or None on rejection / timeout / error."""
    try:
        max_tokens = max(64, min(800, int(len(text) * 1.5 / 4)))
        request_client = client.with_options(timeout=timeout_s) if hasattr(client, "with_options") else client
        resp = request_client.chat.completions.create(
            model=model,
            temperature=0.0,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
        )
        cleaned = resp.choices[0].message.content if resp.choices else ""
        cleaned = (cleaned or "").strip()
    except Exception as e:
        log.warning("smart cleanup failed: %s", type(e).__name__)
        return None

    if not _validate_cleaned(text, cleaned):
        log.info("smart cleanup output rejected by guardrails")
        return None
    return cleaned


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def apply_structure(
    text: str,
    lang: str,
    *,
    client: Any,
    model: str,
    timeout_ms: int,
) -> str:
    """Top-level entry point. Tries deterministic splitters first, then the
    LLM gated by `should_structure`. Returns the original text on any
    skip / failure / rejection."""
    if not text:
        return text

    # 1. Ordinal split (numbered lists).
    ordinal = _split_ordinal_list(text, lang)
    if ordinal is not None:
        log.info("smart cleanup: ordinal-split path")
        return ordinal

    # 2. Comma-only split (bulleted lists).
    comma = _split_comma_list(text, lang)
    if comma is not None:
        log.info("smart cleanup: comma-split path")
        return comma

    # 3. LLM fallback for messier shapes.
    if not should_structure(text, lang):
        return text
    cleaned = structure_text(
        text,
        client=client,
        model=model,
        timeout_s=max(0.1, timeout_ms / 1000.0),
    )
    if cleaned is not None:
        log.info("smart cleanup: llm path")
        return cleaned
    return text
