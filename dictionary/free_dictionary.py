"""Panel-c import alias: Free Dictionary adapter lives in :mod:`dictionary.sources`."""

from dictionary.sources import (
    FREE_DICT_PREFIX,
    FREE_DICTIONARY_API,
    FREE_DICTIONARY_LICENSE,
    FreeDictionarySource,
    free_dictionary_url,
)

__all__ = [
    "FreeDictionarySource",
    "free_dictionary_url",
    "FREE_DICTIONARY_API",
    "FREE_DICT_PREFIX",
    "FREE_DICTIONARY_LICENSE",
]
