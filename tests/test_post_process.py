from wispr_clone.post_process import strip_fillers


def test_strips_simple_um():
    assert strip_fillers("So um I think this works.") == "So I think this works."


def test_strips_multiple_fillers():
    assert strip_fillers("Um, uh, I think er this works.") == "I think this works."


def test_strips_stretched_fillers():
    assert strip_fillers("Ummm uhhh this is fine.") == "This is fine."


def test_case_insensitive():
    assert strip_fillers("UH, this is loud.") == "This is loud."


def test_recapitalizes_when_leading_filler_stripped():
    assert strip_fillers("um hello there") == "Hello there"


def test_preserves_internal_punctuation():
    assert strip_fillers("Hello, um, world!") == "Hello, world!"


def test_collapses_double_spaces():
    assert strip_fillers("hello  um  world") == "Hello world"


def test_does_not_strip_substrings():
    # 'um' inside a word should be preserved
    assert strip_fillers("The umbrella is red.") == "The umbrella is red."
    assert strip_fillers("She is humble.") == "She is humble."


def test_empty_input():
    assert strip_fillers("") == ""


def test_only_fillers_returns_empty():
    assert strip_fillers("um uh er ah") == ""


def test_preserves_apostrophe_words():
    assert strip_fillers("I'm uh going home.") == "I'm going home."
