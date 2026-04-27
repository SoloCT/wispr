from pathlib import Path

import pytest

from wispr_clone.dictionary import build_prompt, load_terms


def test_load_terms_skips_blank_and_comments(tmp_path: Path):
    f = tmp_path / "dictionary.txt"
    f.write_text("# header\nTamcho\n\n# more\nAnthropic\n", encoding="utf-8")
    assert load_terms(f) == ["Tamcho", "Anthropic"]


def test_load_terms_missing_file_returns_empty(tmp_path: Path):
    assert load_terms(tmp_path / "missing.txt") == []


def test_build_prompt_joins_with_comma_space():
    assert build_prompt(["a", "b", "c"]) == "a, b, c"


def test_build_prompt_empty():
    assert build_prompt([]) == ""


def test_build_prompt_truncates_to_budget():
    terms = [f"term{i:03d}" for i in range(200)]
    out = build_prompt(terms, char_budget=50)
    assert len(out) <= 50
    # All emitted terms must be intact (no mid-term cut)
    for t in out.split(", "):
        assert t.startswith("term")


def test_build_prompt_includes_at_least_first_term_when_budget_tight():
    out = build_prompt(["short", "longer_term_here"], char_budget=10)
    assert "short" in out


def test_build_prompt_with_prefix():
    out = build_prompt(["alpha", "beta"], prefix="嘅, 咗")
    assert out.startswith("嘅, 咗, ")
    assert "alpha" in out and "beta" in out


def test_build_prompt_prefix_only_when_no_terms():
    assert build_prompt([], prefix="嘅, 咗") == "嘅, 咗"


def test_build_prompt_prefix_counts_against_budget():
    # prefix `嘅, 咗, 喺` is 7 chars. ", alpha" adds 7 → 14. ", beta" would
    # push to 20 — over budget=15, so it is dropped on a term boundary.
    out = build_prompt(["alpha", "beta", "gamma"], char_budget=15, prefix="嘅, 咗, 喺")
    assert out == "嘅, 咗, 喺, alpha"
