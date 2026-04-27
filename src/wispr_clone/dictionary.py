"""Custom-vocabulary loading. Builds a Whisper `prompt` string from dictionary.txt."""
from __future__ import annotations

from pathlib import Path

# Whisper's prompt limit is ~244 tokens. Approximating tokens at ~4 chars,
# we cap raw character length conservatively to leave headroom.
PROMPT_CHAR_BUDGET = 800


def load_terms(path: Path) -> list[str]:
    """Read dictionary.txt. One term per line; '#' starts a comment; blanks ignored."""
    if not path.exists():
        return []
    terms: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        terms.append(line)
    return terms


def build_prompt(terms: list[str], char_budget: int = PROMPT_CHAR_BUDGET) -> str:
    """Join terms comma-separated, truncating at the character budget on a term boundary."""
    if not terms:
        return ""
    out: list[str] = []
    used = 0
    for t in terms:
        addition = (", " if out else "") + t
        if used + len(addition) > char_budget:
            break
        out.append(t)
        used += len(addition)
    return ", ".join(out)
