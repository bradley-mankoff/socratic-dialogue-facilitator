"""SDF-2 data shapes: vocab literals and dataclasses with dict round-trips.

Stdlib only. Every dataclass has ``to_dict`` / ``from_dict``; there are no
derived fields in state — census, tallies, standing and refuted verdicts are
recomputed by ``board.verdicts`` from ballots + questions, both live and
after journal replay, so reload identity is structural.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Mode = Literal["participates", "facilitates"]
Medium = Literal["async", "live"]
Side = Literal["stands", "rebutted", "for", "against"]
Channel = Literal["explicit", "ambient"]
QKind = Literal[
    "refutation", "close", "mode_switch", "socrates_swap",
    "active_claim_switch", "ingress_selection", "tiebreak",
]
QStatus = Literal["open", "settled", "frozen"]      # frozen = closed by close
HandleKind = Literal["enrolled", "provisional", "bound"]
NodeStatus = Literal["open", "refuted", "unrefuted", "carried_unresolved"]
BoardStatus = Literal["open", "closed"]  # closed is terminal (fused from c)

REFUTATION_SIDES: tuple[str, ...] = ("stands", "rebutted")
GOVERNANCE_SIDES: tuple[str, ...] = ("for", "against")
GOVERNANCE_KINDS: tuple[str, ...] = (
    "close", "mode_switch", "socrates_swap",
    "active_claim_switch", "ingress_selection", "tiebreak",
)


def sides_for(kind: str) -> tuple[str, ...]:
    """Ballot vocabulary for a question kind (fused from c)."""
    return REFUTATION_SIDES if kind == "refutation" else GOVERNANCE_SIDES
Q_KINDS: tuple[QKind, ...] = (
    "refutation", "close", "mode_switch", "socrates_swap",
    "active_claim_switch", "ingress_selection", "tiebreak",
)
MODES: tuple[Mode, ...] = ("participates", "facilitates")
MEDIA: tuple[Medium, ...] = ("async", "live")
SHAPES: tuple[str, ...] = ("3a", "3b")


def _asdict(dc) -> dict[str, Any]:
    """dataclasses.asdict variant that keeps dicts/lists as-is (they are
    already plain values in this model)."""
    from dataclasses import asdict
    return asdict(dc)


@dataclass
class Handle:
    handle_id: str
    display: str
    kind: HandleKind
    is_facilitator: bool

    def to_dict(self) -> dict[str, Any]:
        return _asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Handle":
        return cls(
            handle_id=d["handle_id"],
            display=d["display"],
            kind=d["kind"],
            is_facilitator=d["is_facilitator"],
        )


@dataclass
class Ballot:
    ballot_id: str
    q_id: str
    handle_id: str
    channel: Channel
    side: Side
    reason: str | None
    labeled: bool
    seq: int
    receive_time: float
    withdrawn: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Ballot":
        return cls(
            ballot_id=d["ballot_id"],
            q_id=d["q_id"],
            handle_id=d["handle_id"],
            channel=d["channel"],
            side=d["side"],
            reason=d["reason"],
            labeled=d["labeled"],
            seq=d["seq"],
            receive_time=d["receive_time"],
            withdrawn=d.get("withdrawn", False),
        )


@dataclass
class Question:
    q_id: str
    kind: QKind
    status: QStatus
    subject: str | None        # ce_id (refutation/tiebreak), node_id, mode...
    open_roster: list[str]     # handle_ids present at open, mode-adjusted
    opened_seq: int
    opened_by: str | None
    settled_seq: int | None = None
    outcome: str | None = None  # winning side (or frozen winner) or None

    def to_dict(self) -> dict[str, Any]:
        return _asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Question":
        return cls(
            q_id=d["q_id"],
            kind=d["kind"],
            status=d["status"],
            subject=d["subject"],
            open_roster=list(d.get("open_roster", [])),
            opened_seq=d["opened_seq"],
            opened_by=d["opened_by"],
            settled_seq=d.get("settled_seq"),
            outcome=d.get("outcome"),
        )


@dataclass
class Counterexample:
    ce_id: str
    node_id: str
    shape: Literal["3a", "3b"]
    q_id: str                # 1:1 — every CE has exactly one refutation Q
    tiebreak_invoked: bool = False   # once per CE, ever; set at invocation
    tiebreak_ballot_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Counterexample":
        return cls(
            ce_id=d["ce_id"],
            node_id=d["node_id"],
            shape=d["shape"],
            q_id=d["q_id"],
            tiebreak_invoked=d.get("tiebreak_invoked", False),
            tiebreak_ballot_id=d.get("tiebreak_ballot_id"),
        )


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
        return _asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Node":
        return cls(
            node_id=d["node_id"],
            version=d["version"],
            status=d["status"],
            is_active=d["is_active"],
            ce_ids=list(d.get("ce_ids", [])),
            text=d.get("text", ""),
            defender=d.get("defender"),
        )


@dataclass
class BoardState:
    board_id: str
    x_title: str
    mode: Mode
    medium: Medium
    status: Literal["open", "closed"] = "open"   # closed is terminal
    seq: int = 0                                 # last applied event seq
    handles: dict[str, Handle] = field(default_factory=dict)
    nodes: dict[str, Node] = field(default_factory=dict)
    ces: dict[str, Counterexample] = field(default_factory=dict)
    questions: dict[str, Question] = field(default_factory=dict)
    ballots: dict[str, Ballot] = field(default_factory=dict)
    active_node_id: str | None = None
    socrates_handle_id: str | None = None
    carried_unresolved: list[dict] | None = None  # tray snapshot at close
    canvas: dict | None = None                    # finalized canvas snapshot
    # SDF-9: one pending defense cede per board
    # {"from": handle_id, "to": handle_id, "node_id": active_at_offer} | None
    pending_defense_offer: dict | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "board_id": self.board_id,
            "x_title": self.x_title,
            "mode": self.mode,
            "medium": self.medium,
            "status": self.status,
            "seq": self.seq,
            "handles": {k: v.to_dict() for k, v in self.handles.items()},
            "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
            "ces": {k: v.to_dict() for k, v in self.ces.items()},
            "questions": {k: v.to_dict() for k, v in self.questions.items()},
            "ballots": {k: v.to_dict() for k, v in self.ballots.items()},
            "active_node_id": self.active_node_id,
            "socrates_handle_id": self.socrates_handle_id,
            "carried_unresolved": self.carried_unresolved,
            "canvas": self.canvas,
            "pending_defense_offer": self.pending_defense_offer,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BoardState":
        return cls(
            board_id=d["board_id"],
            x_title=d["x_title"],
            mode=d["mode"],
            medium=d["medium"],
            status=d.get("status", "open"),
            seq=d.get("seq", 0),
            handles={k: Handle.from_dict(v) for k, v in d["handles"].items()},
            nodes={k: Node.from_dict(v) for k, v in d["nodes"].items()},
            ces={k: Counterexample.from_dict(v)
                 for k, v in d["ces"].items()},
            questions={k: Question.from_dict(v)
                       for k, v in d["questions"].items()},
            ballots={k: Ballot.from_dict(v) for k, v in d["ballots"].items()},
            active_node_id=d.get("active_node_id"),
            socrates_handle_id=d.get("socrates_handle_id"),
            carried_unresolved=d.get("carried_unresolved"),
            canvas=d.get("canvas"),
            pending_defense_offer=d.get("pending_defense_offer"),
        )