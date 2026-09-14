"""Panel-c import alias: source failures live in :mod:`dictionary.transport`."""

from dictionary.transport import (
    BadSourceResponse,
    DictionarySourceError,
    SourceUnavailable,
    TransportError,
)

__all__ = [
    "DictionarySourceError",
    "SourceUnavailable",
    "BadSourceResponse",
    "TransportError",
]
