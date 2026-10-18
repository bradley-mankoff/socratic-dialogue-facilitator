"""SDF-16 web seam: keyed Brave provider over its own transport.

The web counterexample path is **explicit-trigger only**: the only way a
Brave request fires is ``search(...)`` called by
:func:`search.service.search_counterexamples` (or a direct call in the
trigger's own tests). No automatic path can reach it:

* the key arrives as a **constructor argument** — no env/config channel,
  so no automatic path can silently arm the web side;
* the token rides the ``X-Subscription-Token`` **header**, never the URL,
  so recordings/logs never leak it;
* construction makes zero network calls; ``search`` performs exactly one
  request, one attempt, no retry/backoff;
* HTTP status is **data** (``unavailable`` + detail) — only
  connection-level failures raise :class:`TransportError`, and even those
  are folded into data by the backend before anything outward sees them.

This module never reads dictionary sources and never touches
``plato.stanford.edu`` — the SEP path (:mod:`search.sep`) performs no I/O
at all, by construction.
"""

from __future__ import annotations

import json
from typing import Protocol, runtime_checkable
from urllib import parse

from dictionary.transport import HttpResponse, TransportError, UrllibTransport
from search.errors import MissingSearchKey
from search.model import (
    WEB_RESULT_LABEL,
    WEB_SEARCH_KIND,
    WEB_SOURCE,
    CounterexampleResult,
    WebHit,
    default_query,
    now_iso,
)

BRAVE_SEARCH_API = "https://api.search.brave.com/res/v1/web/search"
BRAVE_ENGINE = "brave"
LIMIT_MIN = 1
LIMIT_MAX = 20


def clamp_limit(limit: int) -> int:
    """Results-per-request window: Brave accepts 1..20 (pinned by test)."""
    try:
        value = int(limit)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"limit must be an integer, not {limit!r}") from exc
    return max(LIMIT_MIN, min(LIMIT_MAX, value))


def brave_search_url(query: str, count: int) -> str:
    """The one URL shape Brave accepts; query percent-encoded, token-free."""
    return f"{BRAVE_SEARCH_API}?q={parse.quote(str(query))}&count={clamp_limit(count)}"


def brave_headers(key: str) -> dict[str, str]:
    """Auth header — the token lives in the header, never in the URL."""
    return {"X-Subscription-Token": key}


@runtime_checkable
class SearchTransport(Protocol):
    """Seam tests stub; header-aware sibling of the dictionary seam."""

    def get(self, url: str, *, headers: dict) -> HttpResponse: ...


@runtime_checkable
class SearchBackend(Protocol):
    """What a search provider must offer (the only I/O-bearing method)."""

    def search(self, x: str, *, query: str | None = None,
               limit: int = 5) -> CounterexampleResult: ...


class BraveSearchBackend:
    """Keyed web provider (Brave API), one request per trigger.

    Failures-as-data per the plan: 4xx/5xx and malformed payloads become
    ``state="unavailable"`` with a ``detail``; an empty ``web.results``
    list becomes ``state="empty"``; nothing raises outward.
    """

    def __init__(self, key: str, transport: SearchTransport | None = None,
                 *, engine: str = BRAVE_ENGINE, clock=None) -> None:
        if not isinstance(key, str) or not key.strip():
            raise MissingSearchKey(
                "BraveSearchBackend requires a non-blank API key "
                "(constructor argument only — never env/config)")
        self.key = key
        self.transport = transport if transport is not None \
            else UrllibTransport()
        self.engine = engine
        self.clock = clock or now_iso

    def search(self, x: str, *, query: str | None = None,
               limit: int = 5) -> CounterexampleResult:
        q = query if query is not None else default_query(x)
        url = brave_search_url(q, clamp_limit(limit))
        headers = brave_headers(self.key)
        retrieved_at = self.clock()
        try:
            resp = self.transport.get(url, headers=headers)
        except TransportError as exc:
            return self._unavailable(x, q, f"TransportError: {exc}",
                                     retrieved_at)
        if resp.status != 200:
            return self._unavailable(x, q, f"HTTP {resp.status}", retrieved_at)
        try:
            payload = json.loads(resp.body)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            return self._unavailable(x, q, f"invalid JSON: {exc}",
                                     retrieved_at)
        if not isinstance(payload, dict):
            return self._unavailable(x, q, "payload is not a JSON object",
                                     retrieved_at)
        return parse_brave(payload, x=x, query=q, engine=self.engine,
                           retrieved_at=retrieved_at)

    def _unavailable(self, x: str, q: str, detail: str,
                     retrieved_at: str) -> CounterexampleResult:
        return CounterexampleResult(
            x=x, query=q, state="unavailable", hits=[], detail=detail,
            engine=self.engine, retrieved_at=retrieved_at,
        )


def parse_brave(payload: dict, *, x: str, query: str, engine: str,
                retrieved_at: str) -> CounterexampleResult:
    """Shape the Brave payload into the labeled result (pure, no I/O).

    ``web.results`` rows become :class:`WebHit` (title / url /
    description → snippet); a missing or empty list is the explicit
    ``empty`` state. Rows that are not objects are skipped; rows are
    never re-ranked or filtered — the engine's order is the voice's order.
    """
    web = payload.get("web")
    results = web.get("results") if isinstance(web, dict) else None
    rows = [r for r in (results or []) if isinstance(r, dict)]
    if not rows:
        return CounterexampleResult(
            x=x, query=query, state="empty", hits=[], detail=None,
            engine=engine, retrieved_at=retrieved_at,
        )
    hits = [
        WebHit(
            title=str(r.get("title", "")),
            url=str(r.get("url", "")),
            snippet=str(r.get("description", "")),
            engine=engine,
            retrieved_at=retrieved_at,
        )
        for r in rows
    ]
    return CounterexampleResult(
        x=x, query=query, state="ok", hits=hits, detail=None,
        engine=engine, retrieved_at=retrieved_at,
    )


__all__ = [
    "BRAVE_SEARCH_API", "BRAVE_ENGINE",
    "LIMIT_MIN", "LIMIT_MAX",
    "clamp_limit", "brave_search_url", "brave_headers",
    "SearchTransport",
    "SearchBackend", "BraveSearchBackend",
    "parse_brave",
]
