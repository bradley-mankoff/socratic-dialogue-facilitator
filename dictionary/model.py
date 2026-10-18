"""SDF-3 data shapes: chain vocab literals and dataclasses with dict round-trips.

Stdlib only, same conventions as ``board/model.py``: ``Literal`` vocabs,
``to_dict`` / ``from_dict`` on every dataclass, nested ``Cite`` objects
rebuilt explicitly, no derived fields stored (``distinct_sources`` lives
in :mod:`dictionary.chain`).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

SourceName = Literal["wiktionary", "free-dictionary", "merriam-webster"]
SOURCES: tuple[SourceName, ...] = (
    "wiktionary",
    "free-dictionary",
    "merriam-webster",
)
PRIMARY: SourceName = "wiktionary"

SourceStatus = Literal["ok", "no_entry", "unavailable"]
SOURCE_STATUSES: tuple[SourceStatus, ...] = ("ok", "no_entry", "unavailable")

ChainState = Literal["ok", "empty"]
CHAIN_STATES: tuple[ChainState, ...] = ("ok", "empty")

EmptyReason = Literal["all_sources_unavailable", "no_hit"]
EMPTY_REASONS: tuple[EmptyReason, ...] = ("all_sources_unavailable", "no_hit")


@dataclass
class Cite:
    """One dictionary's vote for one sense, carrying its own source record."""

    source: SourceName
    url: str
    access_date: str  # ISO date YYYY-MM-DD; equals ChainResult.pulled_at
    license: str
    raw: dict | None = None  # reserved for payload snippets; always None here
    pageid: int | None = None  # Wiktionary pageid when known (e.g. 56878)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Cite":
        return cls(**d)


@dataclass
class Sense:
    """A ranked canonical gloss: wordings from one anchor + vote cites.

    ``cites`` is in discovery order (anchor first). ``wiktionary_sense_no``
    is the 1-based Wiktionary sense order when Wiktionary anchored the
    sense, else None. ``sense_id`` is the stable ``s{i}`` rank id assigned
    by the chain; it defaults to ``""`` for hand-built senses.
    """

    gloss: str
    pos: str | None
    cites: list[Cite]
    wiktionary_sense_no: int | None = None
    sense_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "gloss": self.gloss,
            "pos": self.pos,
            "cites": [c.to_dict() for c in self.cites],
            "wiktionary_sense_no": self.wiktionary_sense_no,
            "sense_id": self.sense_id,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Sense":
        return cls(
            gloss=d["gloss"],
            pos=d.get("pos"),
            cites=[Cite.from_dict(c) for c in d.get("cites", [])],
            wiktionary_sense_no=d.get("wiktionary_sense_no"),
            sense_id=d.get("sense_id", ""),
        )


@dataclass
class SourceOutcome:
    """Per-source status for one pull: ok / no_entry / unavailable."""

    source: SourceName
    status: SourceStatus
    detail: str | None = None  # "HTTP 522", "HTTP 404", "invalid JSON", ...

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SourceOutcome":
        return cls(**d)


@dataclass
class ChainResult:
    """One pull's outcome: ranked senses, source outcomes, explicit empty state.

    ``senses`` is pre-sorted; list position is the rank (no stored rank
    field).
    """

    x: str
    state: ChainState
    senses: list[Sense]
    empty_reason: EmptyReason | None
    outcomes: list[SourceOutcome]
    pulled_at: str

    def is_empty(self) -> bool:
        return self.state == "empty"

    def check_invariant(self) -> None:
        """Structural invariant: raises AssertionError on violation."""
        if self.state == "ok":
            assert self.senses, "ok result must carry at least one sense"
            assert self.empty_reason is None, "ok result must not set empty_reason"
            for sense in self.senses:
                assert sense.gloss and sense.gloss.strip(), "blank gloss is not a sense"
                assert sense.cites, "every sense carries at least one cite"
                for cite in sense.cites:
                    assert cite.source and cite.url and cite.access_date and cite.license
        elif self.state == "empty":
            assert self.senses == [], "empty state carries zero senses"
            assert self.empty_reason is not None, "empty state needs empty_reason"
        else:  # pragma: no cover - defensive
            raise AssertionError(f"unknown state {self.state!r}")

    @classmethod
    def empty(
        cls,
        x: str,
        empty_reason: EmptyReason,
        outcomes: list[SourceOutcome],
        pulled_at: str,
    ) -> "ChainResult":
        """The explicit empty state: never a blank/zero-sense consensus."""
        return cls(
            x=x,
            state="empty",
            senses=[],
            empty_reason=empty_reason,
            outcomes=list(outcomes),
            pulled_at=pulled_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "x": self.x,
            "state": self.state,
            "senses": [s.to_dict() for s in self.senses],
            "empty_reason": self.empty_reason,
            "outcomes": [o.to_dict() for o in self.outcomes],
            "pulled_at": self.pulled_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ChainResult":
        return cls(
            x=d["x"],
            state=d["state"],
            senses=[Sense.from_dict(s) for s in d.get("senses", [])],
            empty_reason=d.get("empty_reason"),
            outcomes=[SourceOutcome.from_dict(o) for o in d.get("outcomes", [])],
            pulled_at=d["pulled_at"],
        )
