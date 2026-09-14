"""Panel-b/c import alias: Wiktionary adapter lives in :mod:`dictionary.sources`."""

from dictionary.sources import (
    WIKTIONARY_API,
    WIKTIONARY_API_PREFIX,
    WIKTIONARY_ARTICLE,
    WIKTIONARY_LICENSE,
    WiktionarySource,
    parse_wikitext_senses,
    wiktionary_cite_url,
    wiktionary_curid_url,
    wiktionary_url,
)

__all__ = [
    "WiktionarySource",
    "parse_wikitext_senses",
    "wiktionary_url",
    "wiktionary_cite_url",
    "wiktionary_curid_url",
    "WIKTIONARY_API",
    "WIKTIONARY_API_PREFIX",
    "WIKTIONARY_ARTICLE",
    "WIKTIONARY_LICENSE",
]
