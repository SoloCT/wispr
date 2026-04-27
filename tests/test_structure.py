"""Heuristic gate, deterministic splitters, guardrails, and LLM-fallback
tests for the smart-cleanup module. LLM calls are mocked; nothing here
makes a network request."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from wispr_clone.structure import (
    apply_structure,
    should_structure,
    _split_ordinal_list,
    _split_comma_list,
    _validate_cleaned,
)


# ---------------- heuristic gate (LLM-fallback path) ----------------

def test_gate_skips_short_text():
    assert should_structure("buy milk", "en") is False


def test_gate_skips_too_long_text():
    long = "a " * 1500
    assert should_structure(long, "en") is False


def test_gate_skips_pure_prose():
    assert should_structure("the deployment looks healthy and stable today.", "en") is False


def test_gate_triggers_on_ordinal_run_plus_clauses():
    text = "first do the build, second push the branch, third open a pr"
    assert should_structure(text, "en") is True


def test_gate_triggers_on_explicit_phrase():
    text = "as a list, ship it, test it, document it"
    assert should_structure(text, "en") is True


# ---------------- deterministic ordinal splitter ----------------

def test_ordinal_split_user_canonical_example():
    raw = "Alright, here's the list of ingredients. So first you need garlic, second, salt, third, pepper."
    out = _split_ordinal_list(raw, "en")
    assert out == (
        "Alright, here's the list of ingredients:\n"
        "1. garlic\n"
        "2. salt\n"
        "3. pepper"
    )


def test_ordinal_split_drops_intro_when_absent():
    raw = "First do the build, second push the branch, third open a pr."
    out = _split_ordinal_list(raw, "en")
    assert out == "1. do the build\n2. push the branch\n3. open a pr"


def test_ordinal_split_with_count_words():
    raw = "I want one apple, two oranges, three bananas."
    out = _split_ordinal_list(raw, "en")
    assert out == "I want:\n1. apple\n2. oranges\n3. bananas"


def test_ordinal_split_skips_when_only_two_ordinals():
    raw = "first do this and second do that"
    assert _split_ordinal_list(raw, "en") is None


def test_ordinal_split_skips_in_prose():
    raw = "she came in third in the race so we celebrated"
    assert _split_ordinal_list(raw, "en") is None


def test_ordinal_split_does_not_match_one_in_prose():
    # "one" appears but no clause-anchored two/three follow.
    raw = "one of the things to remember is two-fold and important"
    assert _split_ordinal_list(raw, "en") is None


def test_ordinal_split_cantonese_第():
    raw = "我哋要做第一買菜，第二煮飯，第三食飯"
    out = _split_ordinal_list(raw, "yue")
    assert out == "我哋要做:\n1. 買菜\n2. 煮飯\n3. 食飯"


def test_ordinal_split_skips_bare_chinese_numbers():
    # Bare 一二三 deliberately not handled — too ambiguous in Chinese.
    assert _split_ordinal_list("一二三四五", "yue") is None


def test_ordinal_split_strips_chained_lead_ins():
    # "you need to" + "you need to also" — lead-in stripper should peel both.
    raw = "First you need to call mom, second you need to also email dad, third send the report"
    out = _split_ordinal_list(raw, "en")
    assert out == "1. call mom\n2. email dad\n3. send the report"


def test_ordinal_split_returns_none_when_segments_empty_after_clean():
    # All-aux segments — nothing left after lead-in stripping.
    raw = "first you need to, second is, third are"
    assert _split_ordinal_list(raw, "en") is None


# ---------------- deterministic comma-only splitter ----------------

def test_comma_list_short_items_only():
    raw = "eggs, milk, butter, flour."
    out = _split_comma_list(raw, "en")
    assert out == "- eggs\n- milk\n- butter\n- flour"


def test_comma_list_skips_when_first_part_long():
    raw = "I went to the store and got eggs, milk, butter, flour"
    assert _split_comma_list(raw, "en") is None


def test_comma_list_skips_under_three_items():
    assert _split_comma_list("salt, pepper", "en") is None


def test_comma_list_skips_pure_prose():
    assert _split_comma_list("the deployment looks healthy", "en") is None


def test_comma_list_handles_full_width_commas():
    raw = "蘋果，橙，香蕉，西瓜"
    out = _split_comma_list(raw, "yue")
    assert out == "- 蘋果\n- 橙\n- 香蕉\n- 西瓜"


# ---------------- validation guardrails ----------------

def test_validate_accepts_clean_bullet_format():
    # Faithful LLM output: keeps every word, only inserts markers + breaks.
    raw = "first do build, second push branch, third open pr"
    cleaned = "- first do build\n- second push branch\n- third open pr"
    assert _validate_cleaned(raw, cleaned) is True


def test_validate_rejects_too_short_output():
    raw = "first do build, second push branch, third open pr"
    cleaned = "- ok"
    assert _validate_cleaned(raw, cleaned) is False


def test_validate_rejects_too_long_output():
    raw = "first do build, second push branch, third open pr"
    cleaned = "- do build\n- push branch\n- open pr\n" + ("filler text " * 30)
    assert _validate_cleaned(raw, cleaned) is False


def test_validate_rejects_content_token_drop():
    # cleaned drops content nouns ("binary", "main", "team") — should be rejected.
    raw = "first build the binary, second push to main, third notify the team"
    cleaned = "- first build\n- second push\n- third notify"
    assert _validate_cleaned(raw, cleaned) is False


def test_validate_rejects_empty():
    assert _validate_cleaned("first do x, second y, third z", "") is False


# ---------------- apply_structure end-to-end ----------------

def _mock_client(reply: str):
    completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=reply))]
    )
    chat = MagicMock()
    chat.completions.create.return_value = completion
    client = MagicMock()
    client.with_options.return_value = SimpleNamespace(chat=chat)
    client.chat = chat
    return client, chat


def test_apply_structure_uses_deterministic_when_match_no_llm_call():
    client, chat = _mock_client("- whatever the LLM says")
    raw = "Alright, here's the list. First garlic, second salt, third pepper."
    out = apply_structure(
        raw, "en",
        client=client, model="llama-3.1-8b-instant", timeout_ms=3000,
    )
    assert out.startswith("Alright, here's the list:\n1.")
    chat.completions.create.assert_not_called()


def test_apply_structure_uses_comma_split_when_match_no_llm_call():
    client, chat = _mock_client("nope")
    out = apply_structure(
        "eggs, milk, butter, flour", "en",
        client=client, model="m", timeout_ms=3000,
    )
    assert out == "- eggs\n- milk\n- butter\n- flour"
    chat.completions.create.assert_not_called()


def test_apply_structure_falls_back_to_llm_when_no_deterministic_match():
    # Heuristic gate fires (3+ short clauses + trigger phrase) but neither
    # deterministic splitter matches because the first comma-clause is long.
    raw = (
        "I think we should ship today as a list, "
        "prepare the migration script, run the tests, then deploy"
    )
    cleaned = (
        "I think we should ship today as a list:\n"
        "- prepare the migration script\n"
        "- run the tests\n"
        "- then deploy"
    )
    client, chat = _mock_client(cleaned)
    out = apply_structure(
        raw, "en",
        client=client, model="llama-3.1-8b-instant", timeout_ms=3000,
    )
    assert out == cleaned
    chat.completions.create.assert_called_once()


def test_apply_structure_skips_when_gate_fails_and_no_deterministic():
    client, chat = _mock_client("would-be cleaned")
    raw = "today's weather is nice and sunny"
    out = apply_structure(raw, "en", client=client, model="m", timeout_ms=3000)
    assert out == raw
    chat.completions.create.assert_not_called()


def test_apply_structure_falls_back_when_llm_guardrails_reject():
    # Heuristic-gate-only path: LLM returns garbage, guardrails reject,
    # apply_structure returns original.
    raw = (
        "I think we should ship today as a list, "
        "prepare the migration script, run the tests, then deploy"
    )
    client, _ = _mock_client("nope")
    out = apply_structure(
        raw, "en",
        client=client, model="llama-3.1-8b-instant", timeout_ms=3000,
    )
    assert out == raw


def test_apply_structure_falls_back_on_exception():
    raw = (
        "I think we should ship today as a list, "
        "prepare the migration script, run the tests, then deploy"
    )
    client = MagicMock()
    client.with_options.side_effect = RuntimeError("boom")
    out = apply_structure(raw, "en", client=client, model="m", timeout_ms=3000)
    assert out == raw


def test_apply_structure_passthrough_for_empty_text():
    client = MagicMock()
    out = apply_structure("", "en", client=client, model="m", timeout_ms=3000)
    assert out == ""
