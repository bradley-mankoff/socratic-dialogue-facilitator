"""SDF-2 data shapes: vocab literals and dataclasses with dict round-trips.

Stdlib only. Census, tallies, standing and refuted verdicts are
recomputed by ``board.verdicts`` from ballots + questions, both live and
after journal replay, so reload identity is structural.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Medium = Literal["async", "live"]
Side = Literal["stands", "rebutted", "for", "against"]
Channel = Literal["explicit", "ambient"]
QKind = Literal[
    "refutation", "close", "ingress_selection",
]
QStatus = Literal["open", "settled", "frozen"]      # frozen = closed by close
HandleKind = Literal["enrolled", "provisional", "bound"]
NodeStatus = Literal["open", "refuted", "unrefuted", "carried_unresolved"]
BoardStatus = Literal["open", "closed"]  # closed is terminal (fused from c)

REFUTATION_SIDES: tuple[str, ...] = ("stands", "rebutted")
GOVERNANCE_SIDES: tuple[str, ...] = ("for", "against")


def sides_for(kind: str) -> tuple[str, ...]:
    """Ballot vocabulary for a question kind."""
    return REFUTATION_SIDES if kind == "refutation" else GOVERNANCE_SIDES
Q_KINDS: tuple[QKind, ...] = (
    "refutation", "close", "ingress_selection",
)
MEDIA: tuple[Medium, ...] = ("async", "live")
SHAPES: tuple[str, ...] = ("3a", "3b")


@dataclass
class Handle:
    handle_id: str
    display: str
    kind: HandleKind

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Ballot:
    ballot_id: str
    q_id: str
    handle_id: str
    channel: Channel
    side: Side
    reason: str | None
    seq: int
    receive_time: float
    withdrawn: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Question:
    q_id: str
    kind: QKind
    status: QStatus
    subject: str | None        # ce_id (refutation Qs), node_id, ingress...
    open_roster: list[str]     # handle_ids present at open, frozen then
    opened_seq: int
    opened_by: str | None
    settled_seq: int | None = None
    outcome: str | None = None  # winning side (or frozen winner) or None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Counterexample:
    ce_id: str
    node_id: str
    shape: Literal["3a", "3b"]
    q_id: str                # 1:1 — every CE has exactly one refutation Q

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Node:
    node_id: str
    version: int
    status: NodeStatus
    is_active: bool           # exactly one active at a time
    ce_ids: list[str]
    text: str = ""            # claim text (register_node's text argument)
    defender: str | None = None   # SDF-9: role-holder = active claimant

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BoardState:
    board_id: str
    x_title: str
    medium: Medium
    status: Literal["open", "closed"] = "open"   # closed is terminal
    seq: int = 0                                 # last applied event seq
    handles: dict[str, Handle] = field(default_factory=dict)
    nodes: dict[str, Node] = field(default_factory=dict)
    ces: dict[str, Counterexample] = field(default_factory=dict)
    questions: dict[str, Question] = field(default_factory=dict)
    ballots: dict[str, Ballot] = field(default_factory=dict)
    active_node_id: str | None = None
    carried_unresolved: list[dict] | None = None  # tray snapshot at close
    canvas: dict | None = None                    # finalized canvas snapshot

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
