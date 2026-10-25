"""SDF-5 data shapes: board records, claim provenance, operation events.

Stdlib only. Everything here is JSON-able: ``to_dict``/``from_dict`` round
trips are exact so the registry file, the per-X canonical cache and the
sidecar meta log reload structurally (the same rule SDF-2 uses for
``BoardState``).

Two provenance kinds exist and only differ by ``source``/``cites``:

* ``canonical`` — a verbatim copy of one dictionary-chain sense plus the
  cite list that justifies it (``source == "dictionary-chain"``);
* ``original`` — an authored claim with no source tag (``source is None``,
  ``cites == []``).

The claim text stored on the canvas node is always the verbatim ``text``;
provenance never rides inside it (see plan §10).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from dictionary.normalize import normalize_x
from search.model import now_iso

CLAIM_RECORDED = "claim_recorded"
CLAIM_REVISED = "claim_revised"
OPS_EVENT_TYPES: tuple[str, ...] = (CLAIM_RECORDED, CLAIM_REVISED)

# SDF-16 on-demand sidecar events. The OPS tuple value above is frozen
# (pinned by ``test_meta_log_is_separate_from_journal``); on-demand events
# extend what ``MetaLog`` accepts without touching what OPS means.
SEARCH_RECORDED = "search_recorded"
SEP_ADMITTED = "sep_admitted"
ON_DEMAND_EVENT_TYPES: tuple[str, ...] = (SEARCH_RECORDED, SEP_ADMITTED)
ALLOWED_EVENT_TYPES: tuple[str, ...] = (OPS_EVENT_TYPES
                                        + ON_DEMAND_EVENT_TYPES)

TRAY_NAME = "carried_unvoted"
SOURCE_TAG = "dictionary-chain"

# Journal event types the SDF-6 scrutiny API surfaces to SDF-14 (story 21).
# Read straight from ``journal.jsonl`` — the machine stays the only writer
# and no vote event is ever copied into the claim-only ``meta.jsonl``.
VOTE_EVENT_TYPES: tuple[str, ...] = (
    "ballot_cast", "retraction",
)


def slug(text: str) -> str:
    """Path-safe lowercase slug: ``[a-z0-9]`` runs joined by ``-``."""
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:40] or "x"


def make_board_id(x: str, label: str, counter: int) -> str:
    """Readable stable id: ``<slug(x)>--<slug(label)>--<counter:03d>``."""
    return f"{slug(x)}--{slug(label)}--{int(counter):03d}"


def next_label(existing: set[str], base: str) -> str:
    """``base``, then ``base#2``, ``base#3``… (mirrors machine._unique_display).

    Occupancy is judged under ``normalize_x`` on both sides, matching the
    registry key rule that ``Justice`` and ``justice`` are one board.
    """
    base = str(base)
    taken = {normalize_x(str(lab)) for lab in existing}

    def free(candidate: str) -> bool:
        return normalize_x(candidate) not in taken

    if free(base):
        return base
    n = 2
    while not free(f"{base}#{n}"):
        n += 1
    return f"{base}#{n}"


@dataclass
class BoardRecord:
    """Registry row for one board: identity ``(x_norm, label)`` plus mirrors.

    ``medium``/``status`` are *mirrors* of the machine's live state;
    :meth:`server.service.BoardService.sync_registry` is the only writer.
    Views always read the machine, never the mirror.
    """

    board_id: str
    x: str
    x_norm: str
    x_title: str
    label: str
    medium: str = "async"
    status: str = "open"
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BoardRecord":
        x = d.get("x", "")
        return cls(
            board_id=d["board_id"],
            x=x,
            x_norm=d.get("x_norm") or normalize_x(x),
            x_title=d.get("x_title", x),
            label=d["label"],
            medium=d.get("medium", "async"),
            status=d.get("status", "open"),
            created_at=d.get("created_at", ""),
        )


@dataclass
class ClaimProvenance:
    """Why this node's text is what it is (SDF-11 renders this)."""

    node_id: str
    kind: str
    claimed_by: str | None = None
    source: str | None = None
    x: str | None = None
    sense_id: str | None = None
    gloss: str | None = None
    pos: str | None = None
    wiktionary_sense_no: int | None = None
    cite_sources: list[str] = field(default_factory=list)
    cites: list[dict] = field(default_factory=list)
    pulled_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ClaimProvenance":
        return cls(**d)


@dataclass
class ClaimResult:
    """Outcome of one claim/revision operation."""

    board_id: str
    node_id: str
    version: int
    text: str
    is_active: bool
    prev_node_id: str | None
    is_revision: bool
    frozen_q_ids: list[str] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)
    revision_event: dict | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OpenResult:
    """Outcome of ``open_board``: the row, whether it was created, the view."""

    record: BoardRecord
    created: bool
    view: dict = field(default_factory=dict)

    @property
    def board_id(self) -> str:
        return self.record.board_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "board_id": self.board_id,
            "created": self.created,
            "record": self.record.to_dict(),
            "view": dict(self.view),
        }


def canonical_provenance(*, node_id: str, sense: dict, x: str,
                         pulled_at: str | None,
                         claimed_by: str | None) -> ClaimProvenance:
    """Provenance for a claimed canonical: verbatim gloss + its cites."""
    cites = [dict(c) for c in sense.get("cites", [])]
    sources = list(dict.fromkeys(
        str(cite.get("source", "")) for cite in cites if str(cite.get("source", ""))))
    return ClaimProvenance(
        node_id=node_id,
        kind="canonical",
        claimed_by=claimed_by,
        source=SOURCE_TAG,
        x=x,
        sense_id=sense.get("sense_id"),
        gloss=sense.get("gloss"),
        pos=sense.get("pos"),
        wiktionary_sense_no=sense.get("wiktionary_sense_no"),
        cite_sources=sources,
        cites=cites,
        pulled_at=pulled_at,
    )


def original_provenance(*, node_id: str,
                        claimed_by: str | None) -> ClaimProvenance:
    """Provenance for an authored original: no source tag, no cites."""
    return ClaimProvenance(
        node_id=node_id, kind="original", claimed_by=claimed_by,
        source=None, cites=[], cite_sources=[],
    )


@dataclass(frozen=True)
class AllegationResult:
    """Outcome of ``allege``: one CE + its 1:1 refutation Q (story 15)."""

    board_id: str
    node_id: str
    ce_id: str
    q_id: str
    shape: str                 # "3a" | "3b"
    opened_by: str | None      # handle_id or None (anonymous)
    opened_seq: int            # state.questions[q_id].opened_seq

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AllegationResult":
        return cls(**d)


@dataclass(frozen=True)
class VoteResult:
    """Outcome of one ballot ingestion (stories 16–17, 20)."""

    board_id: str
    node_id: str
    ce_id: str | None          # CE subject on refutation Qs
    q_id: str
    ballot_id: str
    handle_id: str
    display: str
    channel: str               # "explicit" | "ambient"
    side: str                  # stands|rebutted (refutation) / for|against
    reason: str | None
    counted: bool              # machine.counted(q_id, handle) is this ballot
    replaced_ballot_id: str | None
    seq: int                   # journal seq of the ballot event
    refuted: bool              # machine.is_refuted(node_id) AFTER the vote

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "VoteResult":
        return cls(**d)


__all__ = [
    "CLAIM_RECORDED", "CLAIM_REVISED", "OPS_EVENT_TYPES", "TRAY_NAME",
    "SOURCE_TAG", "VOTE_EVENT_TYPES",
    "SEARCH_RECORDED", "SEP_ADMITTED", "ON_DEMAND_EVENT_TYPES",
    "ALLOWED_EVENT_TYPES",
    "now_iso", "slug", "make_board_id", "next_label",
    "BoardRecord", "ClaimProvenance", "ClaimResult", "OpenResult",
    "AllegationResult", "VoteResult",
    "canonical_provenance", "original_provenance",
]
