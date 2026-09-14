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

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from board.model import MEDIA, MODES, Medium, Mode  # noqa: F401 (re-export)
from dictionary.normalize import normalize_x

CLAIM_RECORDED = "claim_recorded"
CLAIM_REVISED = "claim_revised"
OPS_EVENT_TYPES: tuple[str, ...] = (CLAIM_RECORDED, CLAIM_REVISED)
TRAY_NAME = "carried_unvoted"
SOURCE_TAG = "dictionary-chain"

CLAIM_KINDS: tuple[str, ...] = ("canonical", "original")


def now_iso() -> str:
    """UTC ISO-8601 timestamp; injectable as ``clock`` for determinism."""
    return datetime.now(timezone.utc).isoformat()


def slug(text: str) -> str:
    """Path-safe lowercase slug: ``[a-z0-9]`` runs joined by ``-``.

    Truncated to 40 chars; a text with no alphanumerics slugs to ``"x"`` so
    the component is never empty and never contains ``/``, ``..`` or
    whitespace.
    """
    runs: list[str] = []
    current = ""
    for ch in str(text).lower():
        if "a" <= ch <= "z" or "0" <= ch <= "9":
            current += ch
        elif current:
            runs.append(current)
            current = ""
    if current:
        runs.append(current)
    out = "-".join(runs)[:40]
    return out or "x"


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

    ``mode``/``medium``/``status`` are *mirrors* of the machine's live state;
    :meth:`server.service.BoardService.sync_registry` is the only writer.
    Views always read the machine, never the mirror.
    """

    board_id: str
    x: str
    x_norm: str
    x_title: str
    label: str
    mode: str = "participates"
    medium: str = "async"
    status: str = "open"
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "board_id": self.board_id,
            "x": self.x,
            "x_norm": self.x_norm,
            "x_title": self.x_title,
            "label": self.label,
            "mode": self.mode,
            "medium": self.medium,
            "status": self.status,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BoardRecord":
        x = d.get("x", "")
        return cls(
            board_id=d["board_id"],
            x=x,
            x_norm=d.get("x_norm") or normalize_x(x),
            x_title=d.get("x_title", x),
            label=d["label"],
            mode=d.get("mode", "participates"),
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
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "claimed_by": self.claimed_by,
            "source": self.source,
            "x": self.x,
            "sense_id": self.sense_id,
            "gloss": self.gloss,
            "pos": self.pos,
            "wiktionary_sense_no": self.wiktionary_sense_no,
            "cite_sources": list(self.cite_sources),
            "cites": [dict(c) for c in self.cites],
            "pulled_at": self.pulled_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ClaimProvenance":
        return cls(
            node_id=d["node_id"],
            kind=d.get("kind", "original"),
            claimed_by=d.get("claimed_by"),
            source=d.get("source"),
            x=d.get("x"),
            sense_id=d.get("sense_id"),
            gloss=d.get("gloss"),
            pos=d.get("pos"),
            wiktionary_sense_no=d.get("wiktionary_sense_no"),
            cite_sources=list(d.get("cite_sources", [])),
            cites=[dict(c) for c in d.get("cites", [])],
            pulled_at=d.get("pulled_at"),
        )


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
        return {
            "board_id": self.board_id,
            "node_id": self.node_id,
            "version": self.version,
            "text": self.text,
            "is_active": self.is_active,
            "prev_node_id": self.prev_node_id,
            "is_revision": self.is_revision,
            "frozen_q_ids": list(self.frozen_q_ids),
            "provenance": dict(self.provenance),
            "revision_event": (
                dict(self.revision_event) if self.revision_event else None),
        }


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
    sources: list[str] = []
    for cite in cites:
        src = str(cite.get("source", ""))
        if src and src not in sources:
            sources.append(src)
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


def build_claim_recorded(payload: dict) -> dict:
    """Event body for a recorded claim (payload only; ``MetaLog`` adds the
    ``seq``/``board_id``/``ts`` envelope)."""
    return {"type": CLAIM_RECORDED, "payload": dict(payload)}


def build_claim_revised(payload: dict) -> dict:
    """Event body for a revision — the SDF-7 ``carried_unvoted`` contract."""
    return {"type": CLAIM_REVISED, "payload": dict(payload)}


__all__ = [
    "CLAIM_RECORDED", "CLAIM_REVISED", "OPS_EVENT_TYPES", "TRAY_NAME",
    "SOURCE_TAG", "CLAIM_KINDS", "MODES", "MEDIA", "Mode", "Medium",
    "now_iso", "slug", "make_board_id", "next_label",
    "BoardRecord", "ClaimProvenance", "ClaimResult", "OpenResult",
    "canonical_provenance", "original_provenance",
    "build_claim_recorded", "build_claim_revised",
]
