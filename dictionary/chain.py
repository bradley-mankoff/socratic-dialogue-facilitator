"""Wiktionary-first consensus chain over injectable HTTP (SDF-3 stories 8/34/35).

Fused (panels a+b+c): panel-a ``consensus`` is canonical (pure merge with
the §6 same-source skip + Jaccard ≥ 0.6 single-best attachment +
``(-agreement, article order)`` ranking, refined here with a stability
tie-break that never changes the canonical order). Layered on top:

* :func:`cluster` (panel-b dedupe) and :func:`rank_senses` (panel-c
  exact-text grouping) over the same threshold constant, all keeping
  Justice-as-virtue and Justice-as-institution distinct.
* :class:`DictionaryChain` speaks ``get`` (a) + ``lookup`` (b) +
  ``search`` (c); ``reset_cache`` + ``clear_cache``; ``build_default_chain``
  + ``default_sources``; ``transport`` + ``fetch``; ``clock``; punct-only
  ``"!!!"`` returns the explicit empty state without spending the
  network (b) while blank/whitespace still raises (a).
* Every result runs :meth:`model.ChainResult.check_invariant` before it
  leaves the chain (panel c); cite ``pageid`` flows from
  :class:`sources.RawSense` (panel b).

Merge policy (never merges distinct senses):
  * one vote per (source, sense); a source's own senses are never
    candidates for its later glosses, so Justice-as-virtue and
    Justice-as-institution stay distinct even at Jaccard 0.8;
  * a secondary gloss attaches to the single best existing sense it does
    not already back, ties going to the earliest, iff Jaccard >= 0.6;
  * otherwise it becomes a new standalone sense.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable

from dictionary.model import (
    PRIMARY,
    ChainResult,
    Sense,
    SourceOutcome,
)
from dictionary.normalize import (
    JACCARD_THRESHOLD,
    gloss_tokens,
    jaccard,
    normalize_gloss,
    normalize_key,
    normalize_x,
)
from dictionary.sources import (
    FreeDictionarySource,
    MerriamWebsterSource,
    RawSense,
    WiktionarySource,
    source_cite,
    stability_for,
)
from dictionary.transport import Transport, UrllibTransport


@dataclass
class SourceResult:
    """One source's outcome plus its raw senses for a single pull."""

    outcome: SourceOutcome
    senses: list[RawSense] = field(default_factory=list)


def distinct_sources(sense: Sense) -> int:
    """Citation-proxy agreement: independent dictionaries backing a sense."""
    return len({str(cite.source) for cite in sense.cites})


def _stability(sense: Sense) -> int:
    return sum(stability_for(str(c.source)) for c in sense.cites)


def _raw_gloss(raw: RawSense) -> str:
    return raw.gloss or (raw.text or "")


def _raw_order(raw: RawSense) -> int:
    return raw.order or (raw.index or 0)


def consensus(
    x: str, pulled_at: str, source_results: list[SourceResult]
) -> ChainResult:
    """Merge per-source results into ranked senses; pure, no I/O."""
    senses: list[Sense] = []
    for result in source_results:
        if str(result.outcome.status) != "ok":
            continue
        source = str(result.outcome.source)
        seen: set[str] = set()
        for raw in result.senses:
            gloss = _raw_gloss(raw)
            key = normalize_gloss(gloss)
            if key in seen:
                continue  # exact within-source duplicate: first occurrence wins
            seen.add(key)
            pageid = getattr(raw, "pageid", None)
            try:
                cite = source_cite(source, x, pulled_at, pageid=pageid)  # type: ignore[arg-type]
            except ValueError:
                cite = source_cite("wiktionary", x, pulled_at)
                cite.source = source  # type: ignore[assignment]
            candidates = [
                sense
                for sense in senses
                if source not in {str(c.source) for c in sense.cites}
            ]
            best: Sense | None = None
            best_score = 0.0
            for sense in candidates:
                score = jaccard(gloss_tokens(gloss), gloss_tokens(sense.gloss))
                if score > best_score:  # strict: ties keep the earliest candidate
                    best_score = score
                    best = sense
            if best is not None and best_score >= JACCARD_THRESHOLD:
                best.cites.append(cite)  # one vote, one sense, wording unchanged
            else:
                if str(source) == PRIMARY:
                    wno = _raw_order(raw) or None
                else:
                    wno = None
                senses.append(
                    Sense(
                        gloss=gloss,
                        pos=raw.pos,
                        cites=[cite],
                        wiktionary_sense_no=wno,
                    )
                )
    # Fix wiktionary_sense_no for the canonical path (RawSense.order is 1-based).
    # The loop above already sets it; this keeps hand-built SourceResults honest.
    ordered = [
        sense
        for _, sense in sorted(
            enumerate(senses),
            key=lambda pair: (
                -distinct_sources(pair[1]),
                -_stability(pair[1]),
                pair[0],
            ),
        )
    ]
    for i, sense in enumerate(ordered):
        sense.sense_id = f"s{i}"
    outcomes = [result.outcome for result in source_results]
    if ordered:
        result = ChainResult(
            x=x,
            state="ok",
            senses=ordered,
            empty_reason=None,
            outcomes=outcomes,
            pulled_at=pulled_at,
        )
    else:
        # Canonical empty reasons are panel-a spellings; the flex string
        # still compares equal to panel-b/c spellings (all_sources_down,
        # no_hits, definition_not_found).
        from dictionary.model import _norm_status

        if outcomes and all(_norm_status(str(o.status)) == "down" for o in outcomes):
            reason = "all_sources_unavailable"
        else:
            reason = "no_hit"
        result = ChainResult.empty(x, reason, outcomes, pulled_at)  # type: ignore[arg-type]
    result.check_invariant()
    return result


def _norm_down(status: str) -> bool:
    from dictionary.model import _norm_status

    return _norm_status(str(status)) == "down"


def _today() -> str:
    return date.today().isoformat()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DictionaryChain:
    """Ordered sources over one transport plus a per-X in-memory cache.

    Accepts ``transport`` (panel a/b) or ``fetch`` (panel c, callable or
    ``get``-style), ``sources`` (explicit list wins), ``clock`` (``() ->
    str`` date or ``() -> datetime``), ``merriam_webster_key`` /
    ``mw_key`` (keyed third vote, never automatic).
    """

    def __init__(
        self,
        sources: list | None = None,
        transport: Any | None = None,
        clock: Callable[[], Any] | None = None,
        mw_key: str | None = None,
        merriam_webster_key: str | None = None,
        fetch: Any | None = None,
        timeout: float = 5.0,
    ) -> None:
        active_transport = transport if transport is not None else fetch
        if sources is None:
            key = merriam_webster_key if merriam_webster_key is not None else mw_key
            if active_transport is None:
                active_transport = UrllibTransport(timeout=timeout)
            sources = [WiktionarySource(), FreeDictionarySource()]
            if key:
                sources.append(MerriamWebsterSource(key))
        self.sources = list(sources)
        self.transport = active_transport
        self.fetch = active_transport
        if clock is None:
            self._clock: Callable[[], str] = _today
        else:
            self._clock = clock  # type: ignore[assignment]
        self._cache: dict[str, ChainResult] = {}

    @property
    def _sources_tuple(self) -> tuple:
        return tuple(self.sources)

    def _pulled_at(self) -> str:
        value = self._clock()
        if isinstance(value, datetime):
            return value.date().isoformat() if value.tzinfo is None else value.isoformat()[:10]
        text = str(value)
        # Panel-b clocks return full ISO timestamps; cites want YYYY-MM-DD.
        return text[:10] if len(text) >= 10 and text[4:5] == "-" else text

    def _now_full(self) -> str:
        value = self._clock()
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    def get(self, x: str) -> ChainResult:
        key = normalize_x(x)
        if not key:
            raise ValueError("x must contain a non-whitespace character")
        cached = self._cache.get(key)
        if cached is not None:
            return cached  # same object: never re-pull mid-dialogue
        # Punct-only queries ("!!!") have no key to look up: explicit empty
        # without spending the network (panel b); blank already raised above.
        if not normalize_key(x):
            result = ChainResult.empty(key, "no_hit", [], self._pulled_at())  # type: ignore[arg-type]
            result.check_invariant()
            self._cache[key] = result
            return result
        pulled_at = self._pulled_at()
        results: list[SourceResult] = []
        for source in self.sources:
            fetch = getattr(source, "fetch", None)
            if callable(fetch):
                try:
                    senses, outcome = fetch(key, self.transport)
                except Exception as exc:  # never raise outward
                    from dictionary.model import SourceOutcome as _SO

                    name = getattr(source, "name", "unknown")
                    senses, outcome = [], _SO(name, "unavailable", f"TransportError: {exc}")  # type: ignore[arg-type]
            else:  # panel-b/c bound-transport sources (query-style)
                query = getattr(source, "query", None)
                outcome = query(key)  # type: ignore[misc]
                senses = list(getattr(outcome, "senses", []))
                from dictionary.model import SourceOutcome as _SO

                outcome = _SO(outcome.source, outcome.status, getattr(outcome, "detail", None))  # type: ignore[arg-type]
            results.append(
                SourceResult(
                    outcome=outcome,
                    senses=list(senses) if str(outcome.status) == "ok" else [],
                )
            )
        result = consensus(key, pulled_at, results)
        self._cache[key] = result
        return result

    # -- panel-b/c aliases -------------------------------------------------
    def lookup(self, x: str) -> ChainResult:
        """Panel-b spelling of :meth:`get` (cached per normalized X)."""
        return self.get(x)

    def search(self, term: str) -> ChainResult:
        """Panel-c spelling of :meth:`get` (never blank consensus)."""
        return self.get(term)

    def reset_cache(self) -> None:
        self._cache.clear()

    def clear_cache(self) -> None:
        """Panel-b spelling of :meth:`reset_cache`."""
        self.reset_cache()

    def stability_of(self, source_name: str) -> int:
        """Panel-c: reliability weight used as a ranking tie-break."""
        return stability_for(source_name)


def build_default_chain(
    transport: Transport | None = None,
    merriam_webster_key: str | None = None,
    timeout: float = 5.0,
    clock: Callable[[], str] | None = None,
    mw_key: str | None = None,
    fetch: Any | None = None,
) -> DictionaryChain:
    """Wiktionary + Free Dictionary by default; MW only when a key is passed."""
    active = transport if transport is not None else fetch
    if active is None:
        active = UrllibTransport(timeout=timeout)
    key = merriam_webster_key if merriam_webster_key is not None else mw_key
    sources: list = [WiktionarySource(), FreeDictionarySource()]
    if key:
        sources.append(MerriamWebsterSource(key))
    return DictionaryChain(sources, active, clock=clock)


def default_sources(transport: Any = None, mw_key: str | None = None) -> list:
    """Panel-b spelling: Wiktionary + Free Dict (+ MW only with key)."""
    sources: list = [WiktionarySource(), FreeDictionarySource()]
    if mw_key:
        from dictionary.merriam_webster import MerriamWebsterSource as _MW

        sources.append(_MW(mw_key))
    return sources


# --------------------------------------------------------------------------
# Panel-b cluster() + panel-c rank_senses() over the same threshold.
# --------------------------------------------------------------------------

def cluster(raw_groups: list[list[RawSense]], access_date: str, x: str = "x") -> list[Sense]:
    """Consensus clustering (panel b): cross-source attach at ≥ 0.6.

    Seeds from the highest-priority source, attaches each lower-source
    sense to the earliest cluster it clears the threshold against while
    skipping clusters that already carry that source (same-source never
    merges). ``x`` feeds cite URLs when a raw sense has no URL of its own.
    """
    from dictionary.model import SOURCE_PRIORITY

    def _priority(source: str) -> int:
        try:
            return list(SOURCE_PRIORITY).index(source)
        except ValueError:
            # Accept hyphen spellings too.
            norm = str(source).replace("-", "_")
            try:
                return list(SOURCE_PRIORITY).index(norm)
            except ValueError:
                return len(SOURCE_PRIORITY)

    def _raw_text(raw: RawSense) -> str:
        return _raw_gloss(raw)

    groups = sorted(
        (g for g in raw_groups if g),
        key=lambda g: _priority(str(getattr(g[0], "source", "wiktionary") or "wiktionary")),
    )
    clusters: list[dict] = []
    for group in groups:
        for raw in group:
            source = str(getattr(raw, "source", None) or "wiktionary")
            target = None
            for candidate in clusters:
                if source in [str(s) for s in candidate["sources"]]:
                    continue
                if jaccard(_raw_text(raw), candidate["text"]) >= JACCARD_THRESHOLD:
                    target = candidate
                    break
            if target is None:
                clusters.append(
                    {"text": _raw_text(raw), "primary": raw, "members": [raw], "sources": [source]}
                )
            else:
                target["members"].append(raw)
                target["sources"].append(source)
    senses: list[Sense] = []
    for i, c in enumerate(clusters):
        primary = c["primary"]
        cites = []
        for raw in c["members"]:
            rsource = str(getattr(raw, "source", None) or "wiktionary")
            url = getattr(raw, "url", None) or source_cite(rsource, x, access_date).url  # type: ignore[arg-type]
            lic = getattr(raw, "license", None)
            if not lic:
                lic = source_cite(rsource, x, access_date).license  # type: ignore[arg-type]
            from dictionary.model import Cite as _Cite

            cites.append(
                _Cite(rsource, url, access_date, lic, pageid=getattr(raw, "pageid", None))  # type: ignore[arg-type]
            )
        senses.append(
            Sense(
                gloss=c["text"],
                pos=getattr(primary, "pos", None),
                cites=cites,
                wiktionary_sense_no=(
                    getattr(primary, "order", None) or getattr(primary, "index", None)
                )
                if str(getattr(primary, "source", "wiktionary")) == PRIMARY
                else None,
                sense_id=f"s{i}",
            )
        )
    return senses


def rank_senses(raws: list[RawSense], access_date: str = "", x: str = "x") -> list[Sense]:
    """Exact-text grouping + evidence ranking (panel c, Jaccard-safe).

    Grouping is exact-text only (case/whitespace folded) — different
    wording is a different sense even when close — so virtue/institution
    stay distinct by construction. Ranking ladder: cross-source
    agreement, then source stability, then listing order. One citation
    per source per sense.
    """
    groups: dict[str, dict] = {}
    for position, raw in enumerate(sorted(raws, key=lambda r: (_raw_order(r), str(getattr(r, "source", ""))))):
        gloss = _raw_gloss(raw)
        key = normalize_gloss(gloss)
        if not key:
            continue
        group = groups.get(key)
        if group is None:
            groups[key] = group = {
                "text": gloss,
                "pos": raw.pos,
                "citations": [],
                "seen": set(),
                "stability": 0,
                "listing_index": position,
            }
        if group["pos"] is None:
            group["pos"] = raw.pos
        rsource = str(getattr(raw, "source", None) or "wiktionary")
        if rsource not in group["seen"]:
            group["seen"].add(rsource)
            url = getattr(raw, "url", None) or source_cite(rsource, x, access_date or _today()).url  # type: ignore[arg-type]
            lic = getattr(raw, "license", None) or source_cite(rsource, x, access_date or _today()).license  # type: ignore[arg-type]
            from dictionary.model import Cite as _Cite

            group["citations"].append(
                _Cite(rsource, url, access_date or _today(), lic, pageid=getattr(raw, "pageid", None))  # type: ignore[arg-type]
            )
            group["stability"] += stability_for(rsource)
    senses = [
        Sense(
            gloss=g["text"],
            pos=g["pos"],
            cites=list(g["citations"]),
            wiktionary_sense_no=None,
            sense_id="",
        )
        for g in groups.values()
    ]
    senses.sort(
        key=lambda s: (
            -distinct_sources(s),
            -sum(stability_for(str(c.source)) for c in s.cites),
            [g["listing_index"] for g in groups.values() if g["text"] == s.gloss][0],
        )
    )
    for i, sense in enumerate(senses):
        sense.sense_id = f"s{i}"
    return senses
