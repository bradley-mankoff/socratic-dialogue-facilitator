"""SDF-16 test helpers: stubbed web transport, tripwire, provider factory.

No pytest import here (mirrors ``tests/stubs.py`` / ``tests/sdf5_stubs.py``)
so any module can use them. The search seam is deliberately separate from
the dictionary seam: ``StubTransport.get(url)`` (dictionary, no headers)
stays byte-frozen; ``StubSearchTransport.get(url, headers=...)`` is the
search-side double.
"""

from __future__ import annotations

import json
from typing import Any

from dictionary.transport import HttpResponse
from tests.stubs import FIXTURES, load_fixture

DATE = "2026-09-13"
TS = "2026-09-13T00:00:00+00:00"

BRAVE_KEY = "test-brave-key"


def brave_response(status: int = 200) -> HttpResponse:
    """The Brave Justice fixture wrapped as a 200 HttpResponse."""
    return HttpResponse(
        status=status, body=json.dumps(load_fixture("brave_justice.json")),
        url="stubbed",
    )


def raw_response(body: str, status: int = 200) -> HttpResponse:
    return HttpResponse(status=status, body=body, url="stubbed")


class StubSearchTransport:
    """Search-side transport double: ``(url, headers)`` recording.

    ``responses`` is a list of :class:`HttpResponse` or Exception instances,
    popped one per call in order (pass the same response twice for two
    identical calls). Records every ``(url, headers)`` pair in ``.calls``
    and the bare URLs in ``.urls`` — the host allow-list and token-header
    tests read those. An extra call beyond the list fails loudly.
    """

    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    @property
    def urls(self) -> list[str]:
        return [url for url, _ in self.calls]

    def get(self, url: str, *, headers: dict | None = None) -> HttpResponse:
        self.calls.append((url, dict(headers or {})))
        assert self.responses, f"unexpected extra search call: {url!r}"
        mapped = self.responses.pop(0)
        if isinstance(mapped, Exception):
            raise mapped
        return mapped


class TripwireSearchTransport:
    """Raises on ANY call: proves unprompted paths never touch the seam."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, *, headers: dict | None = None) -> HttpResponse:
        self.calls.append((url, dict(headers or {})))
        raise AssertionError(f"unprompted web call: {url!r}")


def make_provider(*, transport: Any | None = None, key: str | None = BRAVE_KEY,
                  clock=None):
    """A Brave backend over the Justice fixture (or a given transport)."""
    from search.backend import BraveSearchBackend

    if transport is None:
        transport = StubSearchTransport([brave_response()])
    kwargs = {} if clock is None else {"clock": clock}
    return BraveSearchBackend(key, transport, **kwargs)


class CountingBackend:
    """Records explicit triggers; never performs I/O (counting stub)."""

    def __init__(self, *, clock=None) -> None:
        from search.backend import NullSearchBackend

        self._null = NullSearchBackend(clock=clock)
        self.searches: list[dict] = []

    def search(self, x, *, query=None, limit=5):
        self.searches.append({"x": x, "query": query, "limit": limit})
        return self._null.search(x, query=query, limit=limit)


__all__ = [
    "DATE", "TS", "BRAVE_KEY", "FIXTURES",
    "brave_response", "raw_response",
    "StubSearchTransport", "TripwireSearchTransport",
    "make_provider", "CountingBackend",
]
