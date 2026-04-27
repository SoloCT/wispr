"""Brand-name canonicalization tests. Pure regex; no network."""
from __future__ import annotations

from pathlib import Path

from wispr_clone import brands


# ---------------- Pattern building ----------------

def test_pattern_matches_simple_lowercase():
    p = brands._brand_to_pattern("OpenAI")
    assert p.search("openai")
    assert p.search("OpenAI")
    assert p.search("OPENAI")


def test_pattern_matches_split_form():
    p = brands._brand_to_pattern("OpenAI")
    assert p.search("Open AI")
    assert p.search("open ai")
    assert p.search("OPEN AI")
    assert p.search("Open  AI")  # multi-space


def test_pattern_word_boundary_protection():
    p = brands._brand_to_pattern("OpenAI")
    assert not p.search("openairlines")
    assert not p.search("aiopener")
    assert not p.search("xopenai")


def test_pattern_all_caps_brand():
    p = brands._brand_to_pattern("AWS")
    assert p.search("AWS")
    assert p.search("aws")
    assert p.search("Aws")
    # No false-positive on partial matches.
    assert not p.search("awesome")
    assert not p.search("saws")


def test_pattern_camelcase_iphone():
    p = brands._brand_to_pattern("iPhone")
    assert p.search("iPhone")
    assert p.search("iphone")
    assert p.search("i Phone")
    assert p.search("I Phone")
    assert p.search("IPHONE")


def test_pattern_with_space_in_canonical():
    p = brands._brand_to_pattern("VS Code")
    assert p.search("VS Code")
    assert p.search("vs code")
    assert p.search("vscode")
    assert p.search("VSCode")


def test_pattern_with_dot_punctuation():
    p = brands._brand_to_pattern("Next.js")
    assert p.search("Next.js")
    assert p.search("next.js")
    assert p.search("Next . js")
    assert p.search("NEXT.JS")
    # 'next' alone shouldn't match — the literal dot is required.
    assert not p.search("Next javascript")


def test_pattern_chatgpt_letter_to_caps():
    p = brands._brand_to_pattern("ChatGPT")
    assert p.search("chatgpt")
    assert p.search("ChatGPT")
    assert p.search("Chat GPT")
    assert p.search("chat gpt")


# ---------------- canonicalize_brands ----------------

def test_canonicalize_basic_replacement():
    out = brands.canonicalize_brands(
        "I love openai and chatgpt", ["OpenAI", "ChatGPT"],
    )
    assert out == "I love OpenAI and ChatGPT"


def test_canonicalize_split_form():
    out = brands.canonicalize_brands(
        "I use Open AI and chat gpt daily", ["OpenAI", "ChatGPT"],
    )
    assert out == "I use OpenAI and ChatGPT daily"


def test_canonicalize_punctuated_brand():
    out = brands.canonicalize_brands(
        "we ship next.js apps on node js", ["Next.js", "Node.js"],
    )
    assert out == "we ship Next.js apps on Node.js"


def test_canonicalize_longer_brand_wins_over_shorter():
    # Shorter brand "Open" must NOT clobber inside "OpenAI". Length-desc
    # ordering is the contract; combined_brands sorts that way.
    sorted_brands = sorted(["Open", "OpenAI"], key=lambda s: -len(s))
    out = brands.canonicalize_brands("openai is great", sorted_brands)
    assert out == "OpenAI is great"
    # And 'Open' alone still gets canonicalized when standalone.
    out2 = brands.canonicalize_brands("the door is open", sorted_brands)
    assert out2 == "the door is Open"


def test_canonicalize_empty_text_passthrough():
    assert brands.canonicalize_brands("", ["OpenAI"]) == ""


def test_canonicalize_empty_brands_passthrough():
    assert brands.canonicalize_brands("openai is great", []) == "openai is great"


def test_canonicalize_does_not_match_mid_word():
    # 'openairlines' must not become 'OpenAIrlines'.
    out = brands.canonicalize_brands(
        "we book openairlines flights", ["OpenAI"],
    )
    assert out == "we book openairlines flights"


def test_canonicalize_preserves_surrounding_punctuation():
    out = brands.canonicalize_brands(
        "I love openai, chatgpt, and javascript!",
        ["OpenAI", "ChatGPT", "JavaScript"],
    )
    assert out == "I love OpenAI, ChatGPT, and JavaScript!"


def test_canonicalize_already_correct_unchanged():
    out = brands.canonicalize_brands(
        "I love OpenAI and ChatGPT", ["OpenAI", "ChatGPT"],
    )
    assert out == "I love OpenAI and ChatGPT"


# ---------------- combined_brands ----------------

def test_combined_brands_user_overrides_bundled(tmp_path: Path, monkeypatch):
    # Stub out _load_bundled to a fixed list so this test does not
    # depend on the real assets file.
    monkeypatch.setattr(brands, "_load_bundled", lambda: ["GitHub", "OpenAI"])
    user_file = tmp_path / "dictionary-brands-en.txt"
    user_file.write_text("github\nMyCompany\n", encoding="utf-8")
    out = brands.combined_brands(user_file)
    # User's lowercase 'github' wins on case collision.
    assert "github" in out
    assert "GitHub" not in out
    # User's MyCompany is added.
    assert "MyCompany" in out
    # Untouched bundled entry remains.
    assert "OpenAI" in out


def test_combined_brands_sorted_longest_first(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        brands, "_load_bundled", lambda: ["AI", "OpenAI", "ChatGPT"],
    )
    user_file = tmp_path / "x.txt"
    user_file.write_text("", encoding="utf-8")
    out = brands.combined_brands(user_file)
    # Longest first.
    lengths = [len(b) for b in out]
    assert lengths == sorted(lengths, reverse=True)


def test_combined_brands_missing_user_file_ok(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(brands, "_load_bundled", lambda: ["OpenAI"])
    out = brands.combined_brands(tmp_path / "does-not-exist.txt")
    assert out == ["OpenAI"]


# ---------------- bundled file smoke test ----------------

def test_bundled_brands_loads_real_file():
    """Confirm the bundled assets/brands-en.txt is reachable in dev runs."""
    bundled = brands._load_bundled()
    # Curated highlights — adjust if the bundled list is reorganized.
    assert "OpenAI" in bundled
    assert "ChatGPT" in bundled
    assert "JavaScript" in bundled
    assert "Next.js" in bundled
    # False-positive guards — these must NOT be in the bundled list.
    assert "Apple" not in bundled
    assert "Amazon" not in bundled
    assert "Meta" not in bundled


def test_bundled_brand_canonicalization_end_to_end(tmp_path: Path, monkeypatch):
    """End-to-end smoke: take a sentence with several mis-cased brands,
    feed through canonicalize_brands with combined_brands → all fixed."""
    user_file = tmp_path / "x.txt"
    user_file.write_text("", encoding="utf-8")
    bs = brands.combined_brands(user_file)
    raw = "I'm using openai's chatgpt to write javascript and next.js"
    out = brands.canonicalize_brands(raw, bs)
    assert "OpenAI" in out
    assert "ChatGPT" in out
    assert "JavaScript" in out
    assert "Next.js" in out
