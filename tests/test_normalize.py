"""Normalization helpers (SDF-3): case + whitespace only, punctuation kept."""

from dictionary.normalize import (
    JACCARD_THRESHOLD,
    gloss_tokens,
    jaccard,
    normalize_gloss,
    normalize_x,
)


def test_normalize_x_collapses_whitespace_and_lowercases():
    assert normalize_x("  Civil   Disobedience ") == "civil disobedience"
    assert normalize_x("JUSTICE") == "justice"
    assert normalize_x("\tlaw\n of  nations ") == "law of nations"


def test_gloss_tokens_split_and_lowercase():
    assert gloss_tokens("The Law,  the LAW.") == frozenset(
        {"the", "law,", "law."}
    )
    assert gloss_tokens("  A judge of a court of law. ") == frozenset(
        {"a", "judge", "of", "court", "law."}
    )


def test_jaccard_identical_disjoint_and_partial():
    a = frozenset({"a", "b", "c"})
    b = frozenset({"a", "b", "c"})
    c = frozenset({"x", "y"})
    d = frozenset({"a", "b", "d"})
    assert jaccard(a, b) == 1.0
    assert jaccard(a, c) == 0.0
    assert jaccard(a, d) == 0.5


def test_jaccard_empty_token_sets_is_zero():
    assert jaccard(frozenset(), frozenset()) == 0.0
    assert jaccard(frozenset(), frozenset({"a"})) == 0.0


def test_threshold_is_exactly_point_six():
    assert JACCARD_THRESHOLD == 0.6
    assert normalize_gloss("  The   LAW. ") == "the law."
