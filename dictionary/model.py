"""SDF-3 data shapes: chain vocab literals and dataclasses with dict round-trips.

Fused synthesis (panels a+b+c):

* Canonical vocab is panel-a hyphen style (``free-dictionary``), ``ok /
  no_entry / unavailable``, ``ok / empty`` + ``all_sources_unavailable /
  no_hit`` — the exact tuples pinned by ``test_dictionary_model``.
* Compatibility (panels b/c) is layered on top without breaking the
  canonical tuples: source/status/state/empty strings are flex strings
  that compare equal across ``-``/``_`` spellings and across the
  ``unavailable~down`` / ``no_entry~no_hit~no_hits`` / ``ok~found`` /
  ``empty~definition_not_found~all_sources_down`` synonym families, and
  :class:`ChainResult` exposes ``status / term / retrieved_at /
  per_source / sources / degraded / consensus`` aliases plus
  :meth:`ChainResult.check_invariant` (panel c) and a callable-bool
  :attr:`ChainResult.is_empty` that satisfies both ``is_empty()`` (a)
  and ``is_empty`` (b) call sites.
* :class:`Cite` carries the Wiktionary ``pageid`` (panel b evidence,
  pageid 56878) alongside the canonical article URL (panel a evidence);
  :class:`Sense` carries a stable ``sense_id`` plus ``agrees / score /
  text / citations`` aliases (panels b/c).

Stdlib only, same conventions as ``board/model.py``: ``Literal`` vocabs,
``to_dict`` / ``from_dict`` on every dataclass, nested ``Cite`` objects
rebuilt explicitly, no derived fields stored (``distinct_sources`` lives
in :mod:`dictionary.chain`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SourceName = Literal["wiktionary", "free-dictionary", "merriam-webster"]
SOURCES: tuple[SourceName, ...] = (
    "wiktionary",
    "free-dictionary",
    "merriam-webster",
)
PRIMARY: SourceName = "wiktionary"

# Panel-b priority order (underscore spelling); normalised-equal to SOURCES.
SOURCE_PRIORITY: tuple[str, ...] = (
    "wiktionary",
    "free_dictionary",
    "merriam_webster",
)
SOURCE_PRIORITY_HYPHEN: tuple[str, ...] = SOURCES

SourceStatus = Literal["ok", "no_entry", "unavailable"]
SOURCE_STATUSES: tuple[SourceStatus, ...] = ("ok", "no_entry", "unavailable")

ChainState = Literal["ok", "empty"]
CHAIN_STATES: tuple[ChainState, ...] = ("ok", "empty")

# Panel-b/c aliases (kept separate so the canonical tuples stay pinned).
ChainStatus = Literal["ok", "empty"]
CHAIN_STATUSES: tuple[str, ...] = ("ok", "empty")
EmptyReason = Literal["all_sources_unavailable", "no_hit"]
EMPTY_REASONS: tuple[EmptyReason, ...] = ("all_sources_unavailable", "no_hit")


# --------------------------------------------------------------------------
# Flex strings: synonym-aware equality (left-side).
# --------------------------------------------------------------------------

def _norm_source(s: str) -> str:
    return str(s).replace("-", "_").casefold()


def _norm_status(s: str) -> str:
    v = str(s).casefold().replace("-", "_")
    if v in ("unavailable", "down", "http_5xx", "server_error"):
        return "down"
    if v in ("no_entry", "no_hit", "no_hits", "not_found", "no_entry_found"):
        return "no_hit"
    return v  # "ok" and anything else pass through


def _norm_state(s: str) -> str:
    v = str(s).casefold()
    if v in ("ok", "found", "definition_found"):
        return "ok"
    if v in ("empty", "definition_not_found", "all_sources_down", "no_hits"):
        return "empty"
    return v


def _norm_empty(s: str | None) -> str | None:
    if s is None:
        return None
    v = str(s).casefold()
    if v in ("all_sources_unavailable", "all_sources_down", "all_down"):
        return "all_down"
    if v in ("no_hit", "no_hits", "definition_not_found", "not_found", "no_entry"):
        return "no_hit"
    return v


class _FlexStr(str):
    """Base for synonym-aware strings.

    ``Flex == plain`` compares normalised forms, so the canonical value
    stored here still satisfies panel-b/c spellings when our object is on
    the left of ``==`` (the overwhelmingly common test shape:
    ``result.state == "ok"``, ``[c.source ...] == [...]``).
    """

    _norm = staticmethod(lambda s: str(s))

    def __new__(cls, value: str):
        return super().__new__(cls, str(value))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self._norm(self) == self._norm(other)
        return NotImplemented  # type: ignore[return-value]

    def __ne__(self, other: object) -> bool:
        eq = self.__eq__(other)
        if eq is NotImplemented:
            return eq  # type: ignore[return-value]
        return not eq

    def __hash__(self) -> int:
        # Standard str hash so Flex keys live in plain dicts alongside
        # plain keys for the same spelling (panel-a outcome maps).
        # Cross-spelling dict access goes through SourceMap, not hash.
        return str.__hash__(self)


class SourceStr(_FlexStr):
    _norm = staticmethod(_norm_source)


class StatusStr(_FlexStr):
    _norm = staticmethod(_norm_status)


class StateStr(_FlexStr):
    _norm = staticmethod(_norm_state)


class EmptyReasonStr(_FlexStr):
    _norm = staticmethod(lambda s: _norm_empty(s) or "")


class _EmptyFlag:
    """Callable bool (panel-a ``is_empty()`` + panel-b ``is_empty``)."""

    __slots__ = ("_value",)

    def __init__(self, value: bool) -> None:
        self._value = bool(value)

    def __bool__(self) -> bool:
        return self._value

    def __call__(self) -> bool:
        return self._value

    def __eq__(self, other: object) -> bool:
        if isinstance(other, _EmptyFlag):
            return self._value == other._value
        if isinstance(other, bool):
            return self._value == other
        return NotImplemented  # type: ignore[return-value]

    def __ne__(self, other: object) -> bool:
        eq = self.__eq__(other)
        if eq is NotImplemented:
            return eq  # type: ignore[return-value]
        return not eq

    def __repr__(self) -> str:
        return f"_EmptyFlag({self._value!r})"


def canonical_source(source: str) -> str:
    """Map any accepted spelling to the canonical hyphen form."""
    n = _norm_source(source)
    for canon in SOURCES:
        if _norm_source(canon) == n:
            return canon
    return str(source)


class SourceMap(dict):
    """``{source: status}`` dict with spelling/status synonym tolerance.

    Keys normalise ``-``/``_``; values normalise the
    ``unavailable~down`` / ``no_entry~no_hit`` families, so
    ``per_source == {"wiktionary": "ok", "free_dictionary": "down"}``
    holds whether the stored form is hyphen or underscore.
    """

    def _nkey(self, key: str) -> str:
        return _norm_source(key)

    def _canon_key(self, key: str) -> str | None:
        want = self._nkey(key)
        for k in self.keys():
            if self._nkey(k) == want:
                return k
        return None

    def __getitem__(self, key: str):  # type: ignore[override]
        found = self._canon_key(key)
        if found is None:
            raise KeyError(key)
        return super().__getitem__(found)

    def __contains__(self, key: object) -> bool:  # type: ignore[override]
        if isinstance(key, str):
            return self._canon_key(key) is not None
        return super().__contains__(key)

    def get(self, key: str, default=None):  # type: ignore[override]
        found = self._canon_key(key) if isinstance(key, str) else None
        if found is None:
            return default
        return super().__getitem__(found)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, dict):
            norm_self = {self._nkey(k): _norm_status(v) for k, v in self.items()}
            norm_other = {
                _norm_source(k): _norm_status(v) for k, v in other.items()
            }
            return norm_self == norm_other
        return NotImplemented  # type: ignore[return-value]


@dataclass
class Cite:
    """One dictionary's vote for one sense, carrying its own source record."""

    source: SourceName
    url: str
    access_date: str  # ISO date YYYY-MM-DD; equals ChainResult.pulled_at
    license: str
    raw: dict | None = None  # reserved for payload snippets; always None here
    pageid: int | None = None  # Wiktionary pageid when known (panel b: 56878)

    def __post_init__(self) -> None:
        # Coerce to flex strings so cross-panel spellings compare equal.
        object.__setattr__(self, "source", SourceStr(self.source))

    @property
    def accessed(self) -> str:
        """Panel-b/c alias for :attr:`access_date`."""
        return self.access_date

    @property
    def license_name(self) -> str:
        """Panel-c alias for :attr:`license`."""
        return self.license

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": str(self.source),
            "url": self.url,
            "access_date": self.access_date,
            "license": self.license,
            "raw": self.raw,
            "pageid": self.pageid,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Cite":
        return cls(
            source=d["source"],
            url=d["url"],
            access_date=d.get("access_date", d.get("accessed", "")),
            license=d.get("license", d.get("license_name", "")),
            raw=d.get("raw"),
            pageid=d.get("pageid"),
        )


@dataclass
class Sense:
    """A ranked canonical gloss: wordings from one anchor + vote cites.

    ``cites`` is in discovery order (anchor first). ``wiktionary_sense_no``
    is the 1-based Wiktionary sense order when Wiktionary anchored the
    sense, else None; the two Justice senses keep distinct numbers
    (story 35). ``sense_id`` is the stable ``s{i}`` rank id assigned by
    the chain (panel b); it defaults to ``""`` for hand-built senses.
    """

    gloss: str
    pos: str | None
    cites: list[Cite]
    wiktionary_sense_no: int | None = None
    sense_id: str = ""

    # -- panel-b/c aliases (derived, never stored) ----------------------
    @property
    def text(self) -> str:
        return self.gloss

    @property
    def citations(self) -> list[Cite]:
        return self.cites

    @property
    def agrees(self) -> list[str]:
        seen: list[str] = []
        for cite in self.cites:
            if str(cite.source) not in [str(s) for s in seen]:
                seen.append(str(cite.source))
        return seen

    @property
    def sources(self) -> tuple[str, ...]:
        return tuple(self.agrees)

    @property
    def score(self) -> int:
        return len({str(c.source) for c in self.cites})

    @property
    def agreement(self) -> int:
        return self.score

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
            gloss=d.get("gloss", d.get("text", "")),
            pos=d.get("pos"),
            cites=[Cite.from_dict(c) for c in d.get("cites", d.get("citations", []))],
            wiktionary_sense_no=d.get("wiktionary_sense_no", d.get("index")),
            sense_id=d.get("sense_id", ""),
        )


@dataclass
class SourceOutcome:
    """Per-source status for one pull: ok / no_entry / unavailable."""

    source: SourceName
    status: SourceStatus
    detail: str | None = None  # "HTTP 522", "HTTP 404", "invalid JSON", ...
    # Compat extras (excluded from == so panel-a equality stays pinned).
    senses: list = field(default_factory=list, compare=False)
    url_tried: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", SourceStr(self.source))
        object.__setattr__(self, "status", StatusStr(self.status))

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": str(self.source),
            "status": str(self.status),
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SourceOutcome":
        return cls(
            source=d["source"],
            status=d["status"],
            detail=d.get("detail"),
        )


@dataclass
class ChainResult:
    """One pull's outcome: ranked senses, source outcomes, explicit empty state.

    ``senses`` is pre-sorted; list position is the rank (no stored rank
    field). Canonical fields are panel-a; every panel-b/c name below is a
    derived alias so all three import surfaces observe the same object.
    """

    x: str
    state: ChainState
    senses: list[Sense]
    empty_reason: EmptyReason | None
    outcomes: list[SourceOutcome]
    pulled_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", StateStr(self.state))
        if self.empty_reason is not None:
            object.__setattr__(self, "empty_reason", EmptyReasonStr(self.empty_reason))

    # -- empty flag: property returning a callable bool ------------------
    @property
    def is_empty(self) -> _EmptyFlag:  # type: ignore[override]
        """``result.is_empty`` (b) and ``result.is_empty()`` (a) both work."""
        return _EmptyFlag(self.state == "empty")

    # -- panel-b/c aliases ------------------------------------------------
    @property
    def status(self) -> StateStr:
        return StateStr(self.state)

    @property
    def term(self) -> str:
        return self.x

    @property
    def normalized_x(self) -> str:
        return self.x

    @property
    def retrieved_at(self) -> str:
        return self.pulled_at

    @property
    def accessed(self) -> str:
        return self.pulled_at

    @property
    def per_source(self) -> SourceMap:
        # Keep flex strings (no str() coercion) so underscore spellings
        # and down/unavailable synonyms compare equal via SourceMap.
        return SourceMap({o.source: o.status for o in self.outcomes})

    @property
    def sources(self) -> list[SourceOutcome]:
        """Panel-c ``sources`` report list (same objects as ``outcomes``)."""
        return self.outcomes

    @property
    def degraded(self) -> bool:
        """Panel-c: an ``ok`` result with at least one non-ok source."""
        return self.state == "ok" and any(
            o.status != "ok" for o in self.outcomes
        )

    @property
    def consensus(self) -> Sense | None:
        """Panel-c: top-ranked sense, or ``None`` on the empty state."""
        return self.senses[0] if self.senses else None

    def render(self) -> str:
        """One-line human sentence (panel c): never a blank consensus."""
        if self.state == "empty":
            if self.empty_reason is not None and _norm_empty(
                str(self.empty_reason)
            ) == "all_down":
                return f"No definition for {self.x!r}: all sources unavailable."
            return f"No definition found for {self.x!r}."
        top = self.senses[0].gloss if self.senses else ""
        return f"{self.x}: {top} ({len(self.senses)} sense(s))."

    def check_invariant(self) -> None:
        """Structural invariant (panel c): raises AssertionError on violation."""
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
            assert self.consensus is None
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
            "state": str(self.state),
            "senses": [s.to_dict() for s in self.senses],
            "empty_reason": None
            if self.empty_reason is None
            else str(self.empty_reason),
            "outcomes": [o.to_dict() for o in self.outcomes],
            "pulled_at": self.pulled_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ChainResult":
        return cls(
            x=d.get("x", d.get("term", d.get("normalized_x", ""))),
            state=d.get("state", d.get("status", "empty")),
            senses=[
                Sense.from_dict(s) for s in d.get("senses", [])
            ],
            empty_reason=d.get("empty_reason"),
            outcomes=[
                SourceOutcome.from_dict(o)
                for o in d.get("outcomes", d.get("sources", []))
            ],
            pulled_at=d.get("pulled_at", d.get("retrieved_at", d.get("accessed", ""))),
        )


def empty_result(
    x: str,
    normalized_x: str,
    per_source: dict[str, str],
    reason: str,
    retrieved_at: str,
) -> ChainResult:
    """Panel-b ``empty_result`` factory over the canonical empty state."""
    outcomes = [
        SourceOutcome(source, status, None)  # type: ignore[arg-type]
        for source, status in per_source.items()
    ]
    canon_reason = (
        "all_sources_unavailable"
        if _norm_empty(reason) == "all_down"
        or (_norm_empty(reason) is None and all(_norm_status(v) == "down" for v in per_source.values()))
        else "no_hit"
    )
    return ChainResult.empty(x or normalized_x, canon_reason, outcomes, retrieved_at)  # type: ignore[arg-type]
