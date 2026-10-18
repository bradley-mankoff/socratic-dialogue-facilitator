"""SDF-16 data shapes: web hits, counterexample search results, SEP entries.

Stdlib dataclasses with exact ``to_dict``/``from_dict`` round trips (the
same rule as ``board/model.py`` and ``server/model.py``), so results survive
the meta sidecar reload structurally.

The vocabulary here is deliberately **disjoint** from
:class:`dictionary.model.Sense` / ``ChainResult``:

* ``kind`` is ``"web-search"`` or ``"sep"`` — never a dictionary state;
* ``source`` is ``"brave-web"`` / ``"philosopher-sep"`` — never a
  ``SOURCES`` member, never the ``dictionary-chain`` tag;
* ``canonical`` is hard-coded ``False`` — these are one voice among many,
  never canonical definitions;
* no ``senses`` / ``cites`` / ``empty_reason`` fields exist here, so a
  web result cannot be merged into a ``ChainResult`` by shape accident.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

WEB_SEARCH_KIND = "web-search"
SEP_KIND = "sep"
WEB_SOURCE = "brave-web"
SEP_SOURCE = "philosopher-sep"
SEP_SOURCE_LABEL = "Stanford Encyclopedia of Philosophy (philosopher source)"
SEP_ORIGIN_LINK = "link"
SEP_ORIGIN_PASTE = "paste"
SEP_SITE = "https://plato.stanford.edu"
EXCERPT_MAX_CHARS = 2000
WEB_RESULT_LABEL = "web counterexample — one voice, not a dictionary canonical"

# ``CounterexampleResult.state`` — HTTP status is data; failures land here
# as data too, they never raise outward from ``search()``.
SEARCH_STATES: tuple[str, ...] = ("ok", "empty", "unavailable")

# The whole-board section header SDF-16 folds into ``board_view`` (server
# side). One section under two alias keys, never inside "canonicals".
COUNTEREXAMPLES_SECTION_KIND = "counterexamples"
ON_DEMAND_SECTION_LABEL = (
    "counterexample material — web/SEP voices; never canonicals")

def default_query(x: str) -> str:
    """Fallback query for one X (fused from panel a).

    The provider — never the caller — owns this default so every trigger
    shapes the same query string: ``"<X> counterexample"``.
    """
    return f"{x} counterexample"


def now_iso() -> str:
    """UTC ISO-8601 timestamp; injectable as ``clock`` for determinism."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class WebHit:
    """One web result row, labeled as one voice (never a canonical)."""

    title: str
    url: str
    snippet: str
    engine: str              # "brave" today
    retrieved_at: str        # injected clock, full ISO ts
    kind: str = WEB_SEARCH_KIND
    source: str = WEB_SOURCE
    canonical: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WebHit":
        return cls(**d)


@dataclass
class CounterexampleResult:
    """Outcome of one deliberate web trigger.

    Deliberately NOT a ``ChainResult``: no senses, no cites, no
    ``empty_reason`` overlap. Failures are **data** (``state`` +
    ``detail``); ``search()`` never raises for transport/HTTP problems.
    """

    x: str
    query: str
    state: str               # "ok" | "empty" | "unavailable"
    hits: list[WebHit] = field(default_factory=list)
    detail: str | None = None   # "HTTP 401", "TransportError: ...", ...
    engine: str | None = None
    retrieved_at: str = ""
    kind: str = WEB_SEARCH_KIND
    source: str = WEB_SOURCE
    canonical: bool = False
    label: str = WEB_RESULT_LABEL

    def __post_init__(self) -> None:
        if self.state not in SEARCH_STATES:
            raise ValueError(
                f"state must be one of {SEARCH_STATES}, not {self.state!r}")
        hits = list(self.hits)
        if self.state == "ok" and not hits:
            raise ValueError("state 'ok' requires at least one hit")
        if self.state in ("empty", "unavailable") and hits:
            raise ValueError(
                f"state {self.state!r} carries no hits, got {len(hits)}")
        self.hits = hits

    @property
    def is_empty(self) -> bool:
        """``ok`` carries material; ``empty``/``unavailable`` carry none."""
        return self.state != "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "x": self.x,
            "query": self.query,
            "state": self.state,
            "hits": [h.to_dict() for h in self.hits],
            "detail": self.detail,
            "engine": self.engine,
            "retrieved_at": self.retrieved_at,
            "kind": self.kind,
            "source": self.source,
            "canonical": self.canonical,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CounterexampleResult":
        return cls(
            x=d.get("x", ""),
            query=d.get("query", ""),
            state=d.get("state", "unavailable"),
            hits=[h if isinstance(h, WebHit) else WebHit.from_dict(h)
                  for h in d.get("hits", [])],
            detail=d.get("detail"),
            engine=d.get("engine"),
            retrieved_at=d.get("retrieved_at", ""),
            kind=d.get("kind", WEB_SEARCH_KIND),
            source=d.get("source", WEB_SOURCE),
            canonical=bool(d.get("canonical", False)),
            label=d.get("label", WEB_RESULT_LABEL),
        )


@dataclass
class SepEntry:
    """One SEP voice: a link-out URL OR a pasted excerpt — never a fetch.

    Stored verbatim: the excerpt is the speaker's words as pasted (no
    normalization, no re-quoting), the URL is echoed as given. ``speaker``
    is a display string kept for attribution; it is never enrolled as a
    board handle by the search layer.
    """

    origin: str              # "link" | "paste"
    url: str | None
    excerpt: str | None
    speaker: str | None
    retrieved_at: str
    kind: str = SEP_KIND
    source: str = SEP_SOURCE
    source_label: str = SEP_SOURCE_LABEL
    canonical: bool = False
    x: str | None = None     # the board X this voice was admitted against
    citation: str = ""       # verbatim attribution string, may be empty

    def __post_init__(self) -> None:
        from search.errors import BadSepSource
        if self.origin not in (SEP_ORIGIN_LINK, SEP_ORIGIN_PASTE):
            raise BadSepSource(
                f"origin must be {SEP_ORIGIN_LINK!r} or {SEP_ORIGIN_PASTE!r},"
                f" not {self.origin!r}")
        if self.origin == SEP_ORIGIN_LINK:
            if not (isinstance(self.url, str) and self.url.strip()):
                raise BadSepSource("a SEP link carries a non-blank URL")
            if self.excerpt is not None:
                raise BadSepSource("a SEP link carries no excerpt")
        else:
            if not (isinstance(self.excerpt, str) and self.excerpt.strip()):
                raise BadSepSource(
                    "a pasted SEP excerpt must be a non-blank string")
            if len(self.excerpt) > EXCERPT_MAX_CHARS:
                raise BadSepSource(
                    f"excerpt longer than {EXCERPT_MAX_CHARS} chars "
                    f"({len(self.excerpt)})")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SepEntry":
        return cls(**d)


__all__ = [
    "WEB_SEARCH_KIND", "SEP_KIND", "WEB_SOURCE", "SEP_SOURCE",
    "SEP_SOURCE_LABEL", "SEP_ORIGIN_LINK", "SEP_ORIGIN_PASTE", "SEP_SITE",
    "EXCERPT_MAX_CHARS", "WEB_RESULT_LABEL", "SEARCH_STATES",
    "COUNTEREXAMPLES_SECTION_KIND", "ON_DEMAND_SECTION_LABEL", "default_query",
    "now_iso", "WebHit", "CounterexampleResult", "SepEntry",
]
