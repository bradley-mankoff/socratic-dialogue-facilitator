"""SDF-16 explicit trigger + on-demand renderer (pure, boardless).

:func:`search_counterexamples` is **the only permitted caller** of
``provider.search`` in the whole slice — one deliberate trigger costs
exactly one backend call (never cached into canonicals, never
pre-fetched, never fired by any automatic path). The renderer folds
already-filtered meta event envelopes into the on-demand section body so
``server/views.py`` stays thin and this package stays server-free.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from dictionary.normalize import normalize_x
from search.backend import SearchBackend
from search.model import (
    COUNTEREXAMPLES_SECTION_KIND,
    ON_DEMAND_SECTION_LABEL,
    SEP_KIND,
    SEP_SOURCE_LABEL,
    WEB_SEARCH_KIND,
    CounterexampleResult,
    WebHit,
)

# Fused a+b alias: panel a imports the section header from this module as
# ``ON_DEMAND_KIND`` / ``ON_DEMAND_LABEL``; panel b from ``search.model``.
# Re-export the identical values here so both spellings resolve.
ON_DEMAND_KIND = COUNTEREXAMPLES_SECTION_KIND
ON_DEMAND_LABEL = ON_DEMAND_SECTION_LABEL


def search_counterexamples(x: str, *, provider: SearchBackend,
                           query: str | None = None, limit: int = 5,
                           clock: Callable[[], str] | None = None
                           ) -> CounterexampleResult:
    """Boardless explicit trigger: X → provider → labeled result.

    ``x`` is normalized with the chain's rule (``normalize_x``) so the
    query string matches what canonical pulls searched. ``clock`` (when
    given) restamps the result and its hits with the caller's clock —
    the provider's own clock remains the default.
    """
    xn = normalize_x(x)
    if not xn:
        raise ValueError("x must contain a non-whitespace character")
    result = provider.search(xn, query=query, limit=limit)
    if clock is not None:
        result = _restamp(result, str(clock()))
    return result


def _restamp(result: CounterexampleResult, ts: str) -> CounterexampleResult:
    """Rebuild with one deterministic timestamp (result + every hit)."""
    if result.retrieved_at == ts and all(
            h.retrieved_at == ts for h in result.hits):
        return result
    return replace(
        result, retrieved_at=ts,
        hits=[replace(h, retrieved_at=ts) for h in result.hits],
    )


def render_on_demand(search_events: list[dict],
                     sep_events: list[dict]) -> dict:
    """Fold meta event envelopes into ``{"searches": [...], "sep": [...]}``.

    Both inputs are meta event envelopes (``seq``/``type``/``payload``)
    already filtered by the caller, in file (seq) order; only the
    payloads are surfaced. The caller decides which event types went in,
    so this module never needs the server-side event vocabulary.

    Fused a+b hardening: rows default their ``kind`` (and SEP rows their
    ``source_label``) so a hand-written or older meta row still renders
    labeled; rows are copies, so a caller can never mutate the durable
    log through a view.
    """
    searches: list[dict] = []
    for event in search_events:
        row = _payload(event)
        row.setdefault("kind", WEB_SEARCH_KIND)
        searches.append(row)
    sep: list[dict] = []
    for event in sep_events:
        row = _payload(event)
        row.setdefault("kind", SEP_KIND)
        row.setdefault("source_label", SEP_SOURCE_LABEL)
        sep.append(row)
    return {"searches": searches, "sep": sep}


def _payload(event: Any) -> dict:
    """Accept a meta envelope or a bare payload; return a shallow copy."""
    if isinstance(event, dict) and isinstance(event.get("payload"), dict):
        return dict(event["payload"])
    if isinstance(event, dict):
        return dict(event.get("payload") or {}) if "payload" in event else dict(event)
    return {}


def hit_view(hit: WebHit) -> dict:
    """One web hit as a view row (kept here so views import once)."""
    return hit.to_dict()


__all__ = [
    "ON_DEMAND_KIND", "ON_DEMAND_LABEL",
    "search_counterexamples", "render_on_demand", "hit_view",
]
