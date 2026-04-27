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


# ---------------- Cantonese ----------------

def test_yue_strips_single_syllable_filler():
    assert strip_fillers("嗯今日好攰", lang="yue") == "今日好攰"


def test_yue_strips_stretched_filler():
    # `啊` is intentionally NOT in the filler list because it's a common
    # sentence-final particle — only `嗯`, `呃`, `噉` are stripped.
    assert strip_fillers("嗯嗯嗯我哋走啦", lang="yue") == "我哋走啦"


def test_yue_strips_multi_char_filler():
    assert strip_fillers("我即係想話畀你聽", lang="yue") == "我想話畀你聽"


def test_yue_preserves_question_particle_ah():
    # `啊` survives — it carries meaning in Cantonese.
    assert strip_fillers("好啊", lang="yue") == "好啊"


def test_yue_collapses_full_width_commas():
    assert strip_fillers("好嘢，，，今日", lang="yue") == "好嘢,今日"


def test_en_lang_default_unchanged():
    # Existing English path is the default lang.
    assert strip_fillers("um hello") == "Hello"
