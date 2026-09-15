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
import socket
from typing import Any, Protocol, runtime_checkable
from urllib import error, parse, request

from dictionary.transport import HttpResponse, TransportError
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
USER_AGENT = "socratic-facilitator/0.1 (local self-hosted; contact recorded at deploy)"
DEFAULT_TIMEOUT = 5.0
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


class HeaderUrllibTransport:
    """Default search transport: stdlib urllib, one attempt, no retry.

    Mirrors dictionary semantics: HTTP status is *data* on the returned
    :class:`HttpResponse`; only connection-level failures (DNS, timeout,
    refused) raise ``TransportError``.
    """

    def __init__(self, timeout: float = DEFAULT_TIMEOUT,
                 user_agent: str = USER_AGENT) -> None:
        self.timeout = timeout
        self.user_agent = user_agent

    def get(self, url: str, *, headers: dict | None = None) -> HttpResponse:
        merged = {"User-Agent": self.user_agent, **dict(headers or {})}
        req = request.Request(url, headers=merged)
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return HttpResponse(status=resp.status, body=body, url=url)
        except error.HTTPError as exc:  # 4xx/5xx: status is data, not failure
            try:
                body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            except Exception:
                body = ""
            return HttpResponse(status=exc.code, body=body, url=url)
        except (error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise TransportError(f"{type(exc).__name__}: {exc}") from exc


@runtime_checkable
class SearchBackend(Protocol):
    """What a search provider must offer (the only I/O-bearing method)."""

    def search(self, x: str, *, query: str | None = None,
               limit: int = 5) -> CounterexampleResult: ...


class NullSearchBackend:
    """No web provider configured: every trigger answers with data.

    ``state="unavailable"`` with ``detail="no search provider configured"``
    and zero hits, at **zero transport calls** — a trigger without a
    provider must never invent network I/O to compensate.
    """

    def __init__(self, *, clock=None) -> None:
        self.clock = clock or now_iso

    def search(self, x: str, *, query: str | None = None,
               limit: int = 5) -> CounterexampleResult:
        return CounterexampleResult(
            x=x,
            query=query if query is not None else default_query(x),
            state="unavailable",
            hits=[],
            detail="no search provider configured",
            engine=None,
            retrieved_at=self.clock(),
        )


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
            else HeaderUrllibTransport()
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


def build_default_search_backend(key: str | None = None,
                                 transport: SearchTransport | None = None
                                 ) -> SearchBackend:
    """Keyed → Brave; no key → the explicit no-provider backend.

    The key is a constructor argument by design: no env/config read hides
    in the automatic path, so "no web call without an explicit trigger"
    is provable by construction (F1/F6/F20).
    """
    if key:
        return BraveSearchBackend(key, transport)
    return NullSearchBackend()


__all__ = [
    "BRAVE_SEARCH_API", "BRAVE_ENGINE", "USER_AGENT", "DEFAULT_TIMEOUT",
    "LIMIT_MIN", "LIMIT_MAX",
    "clamp_limit", "brave_search_url", "brave_headers",
    "SearchTransport", "HeaderUrllibTransport",
    "SearchBackend", "NullSearchBackend", "BraveSearchBackend",
    "parse_brave", "build_default_search_backend",
]
