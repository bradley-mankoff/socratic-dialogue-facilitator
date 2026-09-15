"""SDF-16 search errors.

The web counterexample path and the SEP admission path both raise from
this vocabulary so callers catch :class:`SearchError` once. Shapes:

* :class:`MissingSearchKey` — a keyed web backend was constructed without
  a key. Raised **at construction**, never mid-search: arming the web path
  is a deliberate, validated act.
* :class:`NoSearchProvider` — a service-level trigger with no provider
  wired. Raised **before any I/O**: no provider means no call, ever.
* :class:`BadSepSource` — the SEP admission input is not a SEP link or a
  usable pasted excerpt (wrong host, ``http://`` downgrade, blank excerpt,
  both-or-neither, over-size paste). Dual-parented with ``ValueError``
  because SEP shape errors are caller input errors.
"""

from __future__ import annotations


class SearchError(RuntimeError):
    """Base for every ``search/`` failure."""


class MissingSearchKey(SearchError):
    """``BraveSearchBackend(None | "")`` — no key, no backend."""


class NoSearchProvider(SearchError):
    """A deliberate trigger fired with no search provider configured."""


class BadSepSource(SearchError, ValueError):
    """A SEP admission input is neither a SEP link nor a usable paste."""


__all__ = [
    "SearchError",
    "MissingSearchKey",
    "NoSearchProvider",
    "BadSepSource",
]
