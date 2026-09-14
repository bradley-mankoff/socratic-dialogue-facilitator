"""Case + whitespace normalization only — no punctuation handling (SDF-3).

Fused (panels a+b): panel-a helpers are canonical
(``normalize_x`` / ``normalize_gloss`` / ``gloss_tokens`` /
``jaccard(frozenset, frozenset)``); panel-b spellings
(``normalize_text`` / ``normalize_key`` / ``normalize_term`` /
``normalize_sense_text`` / ``tokenize`` / ``jaccard(str, str)``) are
aliases over the same rule. Tokens deliberately keep trailing
punctuation: ``"law"`` and ``"law."`` are different tokens, and the
consensus boundary (Jaccard 0.6) is pinned under this rule.
"""

from __future__ import annotations

import re

JACCARD_THRESHOLD: float = 0.6

_TOKEN_RE = re.compile(r"[a-z0-9']+")


def normalize_x(x: str) -> str:
    """Lowercase, strip and collapse internal whitespace (cache key / x)."""
    return " ".join(x.lower().split())


def normalize_text(s: str) -> str:
    """Panel-b spelling of the same rule (casefold + whitespace collapse)."""
    return re.sub(r"\s+", " ", s).strip().casefold()


def normalize_term(term: str) -> str:
    """Panel-c spelling of :func:`normalize_x`."""
    return normalize_x(term)


def normalize_key(x: str) -> str:
    """Cache key / URL fragment: :func:`normalize_text` then trim trailing
    punctuation so ``'  Justice!! '`` → ``'justice'``.

    Sense texts never go through this path — only the lookup key does.
    """
    return re.sub(r"[^a-z0-9']+$", "", normalize_text(x))


def normalize_gloss(gloss: str) -> str:
    """Same treatment for gloss text; used for exact within-source dedup."""
    return " ".join(gloss.lower().split())


def normalize_sense_text(text: str) -> str:
    """Panel-c spelling of :func:`normalize_gloss`."""
    return normalize_gloss(text)


def gloss_tokens(gloss: str) -> frozenset[str]:
    """Gloss as a token set; punctuation retained on purpose."""
    return frozenset(normalize_gloss(gloss).split())


def tokenize(s: str) -> frozenset[str]:
    """Panel-b spelling: lowercase word tokens as a set, no stopwords."""
    return frozenset(_TOKEN_RE.findall(normalize_text(s)))


def jaccard(a, b) -> float:
    """Token-set Jaccard; two empty sets are defined as 0.0.

    Accepts either two token sets (panel a: ``frozenset``) or two raw
    strings (panel b: tokenized with :func:`tokenize`). Mixed inputs are
    coerced the same way.
    """
    if isinstance(a, str) and isinstance(b, str):
        ta, tb = tokenize(a), tokenize(b)
    elif isinstance(a, str):
        ta, tb = tokenize(a), frozenset(b)
    elif isinstance(b, str):
        ta, tb = frozenset(a), tokenize(b)
    else:
        ta, tb = frozenset(a), frozenset(b)
    union = ta | tb
    return len(ta & tb) / len(union) if union else 0.0
