"""Wiktionary-first consensus chain over injectable HTTP (SDF-3 stories 8/34/35).

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
from typing import Callable

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


def consensus(
    x: str, pulled_at: str, source_results: list[SourceResult]
) -> ChainResult:
    """Merge per-source results into ranked senses; pure, no I/O."""
    senses: list[Sense] = []
    for result in source_results:
        if result.outcome.status != "ok":
            continue
        source = result.outcome.source
        seen: set[str] = set()
        for raw in result.senses:
            gloss = raw.gloss
            key = normalize_x(gloss)
            if key in seen:
                continue  # exact within-source duplicate: first occurrence wins
            seen.add(key)
            pageid = raw.pageid
            try:
                cite = source_cite(source, x, pulled_at, pageid=pageid)
            except ValueError:
                cite = source_cite("wiktionary", x, pulled_at)
                cite.source = source
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
                if source == PRIMARY:
                    wno = raw.order or None
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
        if outcomes and all(o.status == "unavailable" for o in outcomes):
            reason = "all_sources_unavailable"
        else:
            reason = "no_hit"
        result = ChainResult.empty(x, reason, outcomes, pulled_at)
    result.check_invariant()
    return result


def _today() -> str:
    return date.today().isoformat()


class DictionaryChain:
    """Ordered sources over one transport plus a per-X in-memory cache."""

    def __init__(
        self,
        sources: list,
        transport: Transport,
        clock: Callable[[], object] | None = None,
    ) -> None:
        self.sources = list(sources)
        self.transport = transport
        if clock is None:
            self._clock: Callable[[], object] = _today
        else:
            self._clock = clock
        self._cache: dict[str, ChainResult] = {}

    def _pulled_at(self) -> str:
        value = self._clock()
        if isinstance(value, datetime):
            return value.date().isoformat() if value.tzinfo is None else value.isoformat()[:10]
        text = str(value)
        return text[:10] if len(text) >= 10 and text[4:5] == "-" else text

    def get(self, x: str) -> ChainResult:
        key = normalize_x(x)
        if not key:
            raise ValueError("x must contain a non-whitespace character")
        cached = self._cache.get(key)
        if cached is not None:
            return cached  # same object: never re-pull mid-dialogue
        if not normalize_key(x):
            result = ChainResult.empty(key, "no_hit", [], self._pulled_at())
            result.check_invariant()
            self._cache[key] = result
            return result
        pulled_at = self._pulled_at()
        results: list[SourceResult] = []
        for source in self.sources:
            senses, outcome = source.fetch(key, self.transport)
            results.append(
                SourceResult(
                    outcome=outcome,
                    senses=list(senses) if outcome.status == "ok" else [],
                )
            )
        result = consensus(key, pulled_at, results)
        self._cache[key] = result
        return result

    def reset_cache(self) -> None:
        self._cache.clear()


def build_default_chain(
    transport: Transport | None = None,
    merriam_webster_key: str | None = None,
    clock: Callable[[], str] | None = None,
) -> DictionaryChain:
    """Wiktionary + Free Dictionary by default; MW only when a key is passed."""
    active = transport if transport is not None else UrllibTransport()
    sources: list = [WiktionarySource(), FreeDictionarySource()]
    if merriam_webster_key:
        sources.append(MerriamWebsterSource(merriam_webster_key))
    return DictionaryChain(sources, active, clock=clock)
