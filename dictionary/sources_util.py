"""Panel-b import alias: shared source helpers live in :mod:`dictionary.sources`."""

from dictionary.sources import (
    FREE_DICT_PREFIX,
    MERRIAM_WEBSTER_PREFIX,
    WIKTIONARY_API_PREFIX,
    classify_status,
    stability_for,
)

__all__ = [
    "classify_status",
    "stability_for",
    "WIKTIONARY_API_PREFIX",
    "FREE_DICT_PREFIX",
    "MERRIAM_WEBSTER_PREFIX",
]
