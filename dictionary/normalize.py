"""Case + whitespace normalization only — no punctuation handling (SDF-3)."""

from __future__ import annotations

import re

JACCARD_THRESHOLD: float = 0.6


def normalize_x(x: str) -> str:
    """Lowercase, strip and collapse internal whitespace (cache key / x)."""
    return " ".join(x.lower().split())


def normalize_key(x: str) -> str:
    """Cache key / URL fragment: :func:`normalize_x` then trim trailing
    punctuation so ``'  Justice!! '`` → ``'justice'``.

    Sense texts never go through this path — only the lookup key does.
    """
    return re.sub(r"[^a-z0-9']+$", "", normalize_x(x))


def gloss_tokens(gloss: str) -> frozenset[str]:
    """Gloss as a token set; punctuation retained on purpose."""
    return frozenset(normalize_x(gloss).split())


def jaccard(a, b) -> float:
    """Token-set Jaccard; two empty sets are defined as 0.0."""
    ta, tb = frozenset(a), frozenset(b)
    union = ta | tb
    return len(ta & tb) / len(union) if union else 0.0
