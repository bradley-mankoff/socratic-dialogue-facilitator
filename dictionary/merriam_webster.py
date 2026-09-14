"""Panel-b import alias: Merriam-Webster adapter lives in :mod:`dictionary.sources`."""

from dictionary.sources import (
    MERRIAM_WEBSTER_API,
    MERRIAM_WEBSTER_ARTICLE,
    MERRIAM_WEBSTER_LICENSE,
    MERRIAM_WEBSTER_PREFIX,
    MerriamWebsterSource,
    merriam_webster_cite_url,
    merriam_webster_url,
)

__all__ = [
    "MerriamWebsterSource",
    "merriam_webster_url",
    "merriam_webster_cite_url",
    "MERRIAM_WEBSTER_API",
    "MERRIAM_WEBSTER_PREFIX",
    "MERRIAM_WEBSTER_ARTICLE",
    "MERRIAM_WEBSTER_LICENSE",
]
