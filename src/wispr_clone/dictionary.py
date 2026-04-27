"""Custom-vocabulary loading. Builds a Whisper `prompt` string from a per-language dictionary file."""
from __future__ import annotations

from pathlib import Path

# Whisper's prompt limit is ~244 tokens. Approximating tokens at ~4 chars,
# we cap raw character length conservatively to leave headroom.
PROMPT_CHAR_BUDGET = 800

# Cantonese priming string. Whisper's `prompt` field is "previous text
# context", not instructions — instruction-shaped prompts ("please
# transcribe in …") confuse the model.
#
# What we want is **verbatim spoken Cantonese** (書面粵語): 我哋, 嘅, 咗,
# 喺, 嘢, 噉, 啲. Whisper's default with `language="zh"` leans toward
# Standard Written Chinese (書面語) — 我們, 的, 了, 在, 東西 — which
# loses the way it was actually spoken. The fix is to make the prompt
# itself dense, colloquial Cantonese: the model continues in whatever
# register the prompt is in. Particles like 嘢, 喎, 啦, 嘛, 㗎, 先, 啦
# and contractions (啲, 嗰陣) are the strongest register signals.
CANTONESE_PRIMING = (
    "嗨呀，我而家好攰啦，琴日做嘢做到好夜先放工，今朝起身仲未瞓夠。"
    "你呢排點呀？有冇得閒出嚟食個飯傾下偈呀？"
    "我哋去嗰間新開嘅茶餐廳啦，聽講啲嘢食幾好食喎，價錢又抵食。"
    "嗰個老闆都幾搞笑嘅，成日同我哋啲熟客傾偈，佢話佢屋企養咗隻貓好得意。"
    "點解你噉樣諗呀？唔係咁簡單嘅事嚟㗎，而家做乜都要小心啲先得㗎。"
)


def load_terms(path: Path) -> list[str]:
    """Read a dictionary file. One term per line; '#' starts a comment; blanks ignored."""
    if not path.exists():
        return []
    terms: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        terms.append(line)
    return terms


def build_prompt(
    terms: list[str],
    char_budget: int = PROMPT_CHAR_BUDGET,
    prefix: str = "",
) -> str:
    """Join terms comma-separated, truncating at the character budget on a
    term boundary. `prefix` (e.g. a language priming string) is prepended and
    counted against the budget so it cannot be truncated mid-prefix."""
    if not terms and not prefix:
        return ""
    accepted: list[str] = []
    running = 0
    if prefix:
        accepted.append(prefix)
        running = len(prefix)
    for t in terms:
        addition = (", " if accepted else "") + t
        if running + len(addition) > char_budget:
            break
        accepted.append(t)
        running += len(addition)
    return ", ".join(accepted)
