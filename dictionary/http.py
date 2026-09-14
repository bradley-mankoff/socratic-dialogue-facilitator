"""Panel-b/c import alias: HTTP seam lives in :mod:`dictionary.transport`."""

from dictionary.transport import (
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    USER_AGENT,
    BadSourceResponse,
    DictionarySourceError,
    Fetch,
    HttpResponse,
    SourceUnavailable,
    Transport,
    TransportError,
    UrlLibFetch,
    UrllibTransport,
)

__all__ = [
    "HttpResponse",
    "Fetch",
    "Transport",
    "TransportError",
    "DictionarySourceError",
    "SourceUnavailable",
    "BadSourceResponse",
    "UrllibTransport",
    "UrlLibFetch",
    "USER_AGENT",
    "DEFAULT_USER_AGENT",
    "DEFAULT_TIMEOUT",
]
