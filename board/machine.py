"""VerdictMachine — the only mutation entry point for the SDF-2 headless
verdict core.

Every public mutation validates against the current ``BoardState``,
appends exactly one journal event (when a store is attached), applies it
through the same reducer the journal fold uses, then runs settle effects
(which append their own consequence events: q_settled, q_frozen,
node_status_changed, board_closed). Replay therefore
reconstructs the identical state by construction (AC4).
"""

from __future__ import annotations

from datetime import datetime, timezone

from board import verdicts as V
from board.model import (
    MEDIA,
    Q_KINDS,
    REFUTATION_SIDES,
    GOVERNANCE_SIDES,
    SHAPES,
    Ballot,
    BoardState,
    Counterexample,
    Handle,
    Node,
    Question,
)

# --------------------------------------------------------------------------
# Exception hierarchy
# --------------------------------------------------------------------------


class VerdictError(RuntimeError):
    """Base class for every refusal the verdict machine raises."""


class BoardClosed(VerdictError):
    """Mutation attempted on a closed (terminal) board."""


class NodeFrozen(VerdictError):
    """Cast/CE-attach on an inactive (superseded) node's refutation Q."""


class NotDefender(VerdictError):
    """The handle is not the active claim's defender."""


class SideMismatch(VerdictError):
    """Ballot side does not match the Q kind's vocabulary."""


class QNotOpen(VerdictError):
    """Cast/retract on a Q that is not open."""


class UnknownHandle(VerdictError):
    """No such handle."""


class UnknownQuestion(VerdictError):
    """No such Q."""


class UnknownNode(VerdictError):
    """No such node."""


class UnknownCounterexample(VerdictError):
    """No such counterexample."""


class NoBoard(VerdictError):
    """Mutation before any board was created on this machine."""


class BoardAlreadyExists(VerdictError):
    """create_board on a machine that already holds a board."""


class NotActiveNode(NodeFrozen):
    """Inactive-node refusal with a finer-grained name (fused from c).

    Subclasses ``NodeFrozen`` so existing ``except NodeFrozen`` handlers
    keep catching inactive-node refuses while new code can catch the
    narrower ``NotActiveNode``.
    """


# --------------------------------------------------------------------------
# The reducer — the single fold used live and for replay
# --------------------------------------------------------------------------

EVENT_TYPES = (
    "board_created", "handle_enrolled", "name_bound",
    "node_registered", "q_opened", "ballot_cast", "ambient_recorded",
    "retraction", "medium_toggled",
    "node_status_changed", "q_settled", "q_frozen",
    "board_closed",
)

# Journal types the sdf-zj6.1 cut dropped (the Socrates seat and its
# ``socrates_set`` event, the facilitator modes and ``mode_switch_applied``,
# the tiebreak and its ballot, the active-claim switch and the defense
# hand-over). Old journals, such as Symposiums started on the pull-request-
# #26 code, still hold them: replay skips them so those boards still open.
# The skip only drops cut governance — claims and counterexamples replay
# exactly as journaled; ballots a pre-cut switch to facilitates mode
# withdrew count again after replay (the withdrawal rode with the switch).
DROPPED_EVENT_TYPES = frozenset({
    "socrates_set", "mode_switch_applied", "tiebreak_ballot_cast",
    "active_switch_applied", "defense_cede_offered",
    "defense_cede_accepted", "defense_cede_declined",
    "defense_cede_withdrawn",
})


def _empty_state() -> BoardState:
    return BoardState(board_id="", x_title="",
                      medium="async")


def _frozen_outcome(state: BoardState, q_id: str) -> str | None:
    """Winner-or-None recorded on a Q the moment it freezes."""
    q = state.questions[q_id]
    if q.kind == "refutation":
        return V.refutation_outcome(state, q.subject)
    return V.governance_passed(state, q_id)


def _apply(state: BoardState, event: dict) -> None:
    """Total, deterministic reducer: one case per journal event type."""
    state.seq = event["seq"]
    t = event["type"]
    p = event["payload"]
    if t in DROPPED_EVENT_TYPES:
        return
    if t == "board_created":
        state.board_id = p["board_id"]
        state.x_title = p["x_title"]
        state.medium = p.get("medium", "async")
        state.status = "open"
    elif t == "handle_enrolled":
        state.handles[p["handle_id"]] = Handle(
            p["handle_id"], p["display"], p["kind"])
    elif t == "name_bound":
        h = state.handles[p["handle_id"]]
        h.display = p["display"]
        h.kind = "bound"
    elif t == "node_registered":
        node = Node(p["node_id"], p["version"], "open", True, [],
                    p.get("text", ""), p.get("defender"))
        prev = p.get("prev_active_node_id")
        if prev is not None:
            state.nodes[prev].is_active = False
        state.nodes[node.node_id] = node
        state.active_node_id = node.node_id
    elif t == "q_opened":
        state.questions[p["q_id"]] = Question(
            p["q_id"], p["kind"], "open", p.get("subject"),
            list(p.get("roster", [])), event["seq"], p.get("opened_by"))
        if p["kind"] == "refutation":
            ce = Counterexample(p["ce_id"], p["node_id"], p["shape"],
                                p["q_id"])
            state.ces[ce.ce_id] = ce
            state.nodes[p["node_id"]].ce_ids.append(ce.ce_id)
    elif t in ("ballot_cast", "ambient_recorded"):
        # Old journals may still carry a "labeled" key on ballot_cast
        # payloads; it is ignored: the tiebreak that wrote True is dropped.
        ballot = Ballot(
            p["ballot_id"], p["q_id"], p["handle_id"], p["channel"],
            p["side"], p.get("reason"),
            event["seq"], p["receive_time"])
        state.ballots[ballot.ballot_id] = ballot
    elif t == "retraction":
        state.ballots[p["ballot_id"]].withdrawn = True
    elif t == "medium_toggled":
        state.medium = p["medium"]
    elif t == "node_status_changed":
        state.nodes[p["node_id"]].status = p["status"]
    elif t == "q_settled":
        q = state.questions[p["q_id"]]
        q.status = "settled"
        q.settled_seq = event["seq"]
        q.outcome = p["outcome"]
    elif t == "q_frozen":
        q = state.questions[p["q_id"]]
        q.status = "frozen"
        q.settled_seq = event["seq"]
        q.outcome = p["outcome"]
    elif t == "board_closed":
        state.status = "closed"
        state.carried_unresolved = p["carried_unresolved"]
        state.canvas = p["canvas"]
        was_open = {q_id for q_id, q in state.questions.items()
                    if q.status == "open"}
        for q in state.questions.values():
            if q.status == "open":
                q.status = "frozen"
                q.settled_seq = event["seq"]
                q.outcome = _frozen_outcome(state, q.q_id)
        for node in state.nodes.values():
            if node.status == "refuted":
                continue
            if any(state.ces[ce].q_id in was_open for ce in node.ce_ids):
                node.status = "carried_unresolved"
    else:
        raise ValueError(f"unknown event type: {t}")


def fold_events(events: list[dict], initial: BoardState | None = None) -> BoardState | None:
    """Fold journal events through the live reducer; None when empty."""
    state = initial
    for event in events:
        if state is None:
            state = _empty_state()
        _apply(state, event)
    return state


def _iso_ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unique_display(state: BoardState, base: str) -> str:
    """Duplicate displays auto-suffix: name, name#2, name#3..."""
    taken = {h.display for h in state.handles.values()}
    if base not in taken:
        return base
    k = 2
    while f"{base}#{k}" in taken:
        k += 1
    return f"{base}#{k}"


# --------------------------------------------------------------------------
# The machine
# --------------------------------------------------------------------------


class VerdictMachine:
    """Headless verdict core. ``store=None`` runs purely in memory;
    with a ``JsonlStore`` every mutation persists before it returns."""

    def __init__(self, store=None, board_id: str | None = None):
        self._store = store
        self._board_id = board_id
        self._state: BoardState | None = None
        self._events: list[dict] = []
        if store is not None and board_id is not None:
            self._state = store.load_state(board_id)
            if self._state is not None:
                self._events = store.read_all(board_id)

    @classmethod
    def in_memory(cls, medium: str = "async") -> "VerdictMachine":
        """Fresh memory-only machine with a ready board (AC1–AC3 tests)."""
        m = cls()
        m.create_board("board-in-memory", "Justice (Republic Book I)",
                       medium=medium)
        return m

    # -- state access ------------------------------------------------------

    @property
    def state(self) -> BoardState:
        return self._state

    @property
    def events(self) -> list[dict]:
        """Journal events applied so far (sequence order, mutable copies)."""
        return [dict(e) for e in self._events]

    def snapshot(self) -> dict:
        self._require_board()
        return self._state.to_dict()

    # -- internals ---------------------------------------------------------

    def _require_board(self) -> None:
        if self._state is None:
            raise NoBoard("no board created")

    def _check_open(self) -> None:
        self._require_board()
        if self._state.status == "closed":
            raise BoardClosed(f"board {self._state.board_id} is closed")

    def _commit(self, etype: str, payload: dict) -> dict:
        self._require_board()
        seq = self._state.seq + 1
        event = {"seq": seq, "type": etype, "payload": payload,
                 "ts": _iso_ts()}
        if self._store is not None:
            self._store.append(self._board_id, event)
        _apply(self._state, event)
        self._events.append(event)
        return event

    def _get_q(self, q_id: str) -> Question:
        q = self._state.questions.get(q_id)
        if q is None:
            raise UnknownQuestion(f"unknown question: {q_id}")
        return q

    def _get_handle(self, handle_id: str) -> Handle:
        h = self._state.handles.get(handle_id)
        if h is None:
            raise UnknownHandle(f"unknown handle: {handle_id}")
        return h

    def _open_roster(self) -> list[str]:
        return sorted(V.franchise(self._state))

    def _recompute_active_node_status(self) -> None:
        nid = self._state.active_node_id
        if nid is None:
            return
        new_status = ("refuted" if V.is_refuted(self._state, nid)
                      else "unrefuted")
        node = self._state.nodes[nid]
        if node.status != new_status:
            self._commit("node_status_changed",
                         {"node_id": nid, "status": new_status})

    def _settle_tail(self, q_id: str) -> None:
        """Settle effects after any tally-changing mutation (§6)."""
        q = self._state.questions[q_id]
        if q.kind == "refutation":
            self._recompute_active_node_status()
            return
        side = V.governance_passed(self._state, q_id)
        if side is None:
            return
        self._commit("q_settled", {"q_id": q_id, "outcome": side})
        if side != "for":
            return                    # only a settled 'for' is a mandate
        if q.kind == "close":
            self.close_board(q_id)
        # ingress_selection: settle + record the outcome; consumption
        # belongs to downstream slices (SDF-11/18).

    # -- board + identities -------------------------------------------------

    def create_board(self, board_id: str, x_title: str,
                     medium: str = "async") -> BoardState:
        if self._state is not None:
            raise BoardAlreadyExists(
                f"board {self._state.board_id} already created")
        if not board_id or not isinstance(board_id, str):
            raise ValueError("board_id required")
        if not x_title or not isinstance(x_title, str):
            raise ValueError("x_title required")
        if medium not in MEDIA:
            raise ValueError(f"medium must be one of {MEDIA}")
        self._board_id = board_id
        self._state = _empty_state()
        self._commit("board_created", {
            "board_id": board_id, "x_title": x_title,
            "medium": medium,
        })
        return self._state

    def enroll_handle(self, display: str,
                      kind: str = "enrolled") -> str:
        self._check_open()
        if not display or not isinstance(display, str):
            raise ValueError("display required")
        if kind not in ("enrolled", "provisional", "bound"):
            raise ValueError(f"invalid handle kind: {kind}")
        handle_id = f"h{len(self._state.handles) + 1}"
        display = _unique_display(self._state, display)
        self._commit("handle_enrolled", {
            "handle_id": handle_id, "display": display,
            "kind": kind,
        })
        return handle_id

    def bind_name(self, provisional_handle_id: str, display: str) -> str:
        self._check_open()
        provisional_handle_id = self._get_handle(
            provisional_handle_id).handle_id
        if not display or not isinstance(display, str):
            raise ValueError("display required")
        display = _unique_display(self._state, display)
        self._commit("name_bound", {
            "handle_id": provisional_handle_id, "display": display,
        })
        return provisional_handle_id

    def defender(self) -> str | None:
        """Active claim's defender handle_id (``None`` while no claim)."""
        self._require_board()
        node_id = self._state.active_node_id
        if node_id is None:
            return None
        node = self._state.nodes.get(node_id)
        return node.defender if node is not None else None

    def require_defender(self, handle_id: str) -> str:
        """Return ``handle_id`` when it is the active defender, else refuse."""
        self._require_board()
        current = self.defender()
        if current is None:
            raise NotDefender("no defense to hold on this board")
        if current != handle_id:
            raise NotDefender(
                f"handle {handle_id!r} is not the active defender")
        return handle_id

    # -- canvas --------------------------------------------------------------

    def _supersede(self, prev: str | None) -> None:
        if prev is None:
            return
        node = self._state.nodes[prev]
        new_status = ("refuted" if V.is_refuted(self._state, prev)
                      else "unrefuted")
        if node.status != new_status:
            self._commit("node_status_changed",
                         {"node_id": prev, "status": new_status})
        for ce_id in node.ce_ids:
            q_id = self._state.ces[ce_id].q_id
            if self._state.questions[q_id].status == "open":
                outcome = V.refutation_outcome(self._state, ce_id)
                self._commit("q_frozen",
                             {"q_id": q_id, "outcome": outcome})

    def register_node(self, node_id: str, text: str,
                      defender: str | None = None) -> str:
        self._check_open()
        if not node_id or not isinstance(node_id, str):
            raise ValueError("node_id required")
        if node_id in self._state.nodes:
            raise ValueError(f"node {node_id} already registered")
        if not isinstance(text, str):
            raise ValueError("text required")
        if defender is not None:
            self._get_handle(defender)
        prev = self._state.active_node_id
        version = max((n.version for n in self._state.nodes.values()),
                      default=0) + 1
        self._commit("node_registered", {
            "node_id": node_id, "text": text, "version": version,
            "prev_active_node_id": prev, "defender": defender,
        })
        self._supersede(prev)
        return node_id

    def open_refutation_q(self, node_id: str, shape: str,
                          opened_by: str | None = None
                          ) -> tuple[str, str]:
        """Attach a counterexample to ``node_id``; CE and its Q are 1:1."""
        self._check_open()
        node = self._state.nodes.get(node_id)
        if node is None:
            raise UnknownNode(f"unknown node: {node_id}")
        if not node.is_active:
            raise NodeFrozen(f"node {node_id} is inactive")
        if shape not in SHAPES:
            raise ValueError(f"shape must be one of {SHAPES}")
        if opened_by is not None:
            self._get_handle(opened_by)
        ce_id = f"ce{len(self._state.ces) + 1}"
        q_id = f"q{len(self._state.questions) + 1}"
        self._commit("q_opened", {
            "q_id": q_id, "kind": "refutation", "subject": ce_id,
            "node_id": node_id, "ce_id": ce_id, "shape": shape,
            "opened_by": opened_by, "roster": self._open_roster(),
        })
        return ce_id, q_id

    def open_governance_q(self, kind: str, subject: str | None = None,
                          opened_by: str | None = None) -> str:
        self._check_open()
        if kind not in Q_KINDS or kind == "refutation":
            raise ValueError(f"invalid governance kind: {kind}")
        if opened_by is not None:
            self._get_handle(opened_by)
        q_id = f"q{len(self._state.questions) + 1}"
        self._commit("q_opened", {
            "q_id": q_id, "kind": kind, "subject": subject,
            "opened_by": opened_by, "roster": self._open_roster(),
        })
        return q_id

    # -- votes ----------------------------------------------------------------

    def cast(self, q_id: str, handle_id: str, channel: str, side: str,
             reason: str | None = None,
             receive_time: float | None = None) -> str:
        self._check_open()
        q = self._get_q(q_id)
        self._get_handle(handle_id)
        if q.kind == "refutation":
            ce = self._state.ces[q.subject]
            if not self._state.nodes[ce.node_id].is_active:
                raise NodeFrozen(
                    f"node {ce.node_id} is inactive; re-votes are refused")
        if q.status != "open":
            raise QNotOpen(f"question {q_id} is {q.status}")
        if channel not in ("explicit", "ambient"):
            raise ValueError(f"invalid channel: {channel}")
        valid_sides = (REFUTATION_SIDES if q.kind == "refutation"
                       else GOVERNANCE_SIDES)
        if side not in valid_sides:
            raise SideMismatch(
                f"side {side!r} does not match {q.kind} Q vocabulary")
        if receive_time is None:
            receive_time = float(self._state.seq + 1)
        else:
            receive_time = float(receive_time)
        ballot_id = f"b{len(self._state.ballots) + 1}"
        self._commit("ballot_cast", {
            "ballot_id": ballot_id, "q_id": q_id, "handle_id": handle_id,
            "channel": channel, "side": side, "reason": reason,
            "receive_time": receive_time,
        })
        self._settle_tail(q_id)
        return ballot_id

    def record_ambient(self, q_id: str, handle_id: str, side: str,
                       receive_time: float | None = None) -> str:
        return self.cast(q_id, handle_id, "ambient", side,
                         receive_time=receive_time)

    def retract(self, q_id: str, handle_id: str,
                receive_time: float | None = None) -> None:
        """Ambient-only touch: withdraws the counted ambient ballot, never
        an explicit one. No-op when there is nothing ambient to withdraw."""
        self._check_open()
        q = self._get_q(q_id)
        self._get_handle(handle_id)
        if q.status != "open":
            raise QNotOpen(f"question {q_id} is {q.status}")
        counted = V.counted_ballot(self._state, q_id, handle_id)
        if counted is None or counted.channel == "explicit":
            return
        self._commit("retraction", {
            "q_id": q_id, "handle_id": handle_id,
            "ballot_id": counted.ballot_id,
        })
        self._settle_tail(q_id)

    def settle(self, q_id: str) -> str | None:
        """Force a resolve attempt. Governance Qs settle on majority;
        refutation Qs report the current verdict without settling."""
        self._check_open()
        q = self._get_q(q_id)
        if q.kind == "refutation":
            if q.subject is None:
                return None
            return V.refutation_outcome(self._state, q.subject)
        if q.status == "settled":
            return q.outcome
        side = V.governance_passed(self._state, q_id)
        if side is not None:
            self._settle_tail(q_id)
        return side

    # -- governance effects ---------------------------------------------------

    def toggle_medium(self, medium: str) -> None:
        """Field write only: no census mutation, no re-tally of settled Qs."""
        self._check_open()
        if medium not in MEDIA:
            raise ValueError(f"medium must be one of {MEDIA}")
        self._commit("medium_toggled", {"medium": medium})

    def close_board(self, q_id: str) -> None:
        """Fire the close effect: only via a settled close Q with outcome
        "for". One board_closed event freezes every open Q, snapshots the
        unresolved tray and the finalized canvas, and closes the board."""
        self._require_board()
        if self._state.status == "closed":
            return      # SDF-8: the board is terminal; never snapshot twice
        q = self._get_q(q_id)
        if q.kind != "close" or q.status != "settled" or q.outcome != "for":
            raise VerdictError(
                "close requires a settled close Q with outcome 'for'")
        tray, canvas = self._close_snapshot()
        self._commit("board_closed", {
            "q_id": q_id, "carried_unresolved": tray, "canvas": canvas,
        })

    def _close_snapshot(self) -> tuple[list[dict], dict]:
        state = self._state
        was_open = {q_id for q_id, q in state.questions.items()
                    if q.status == "open"}
        tray: list[dict] = []
        tray_nodes: set[str] = set()
        for node in state.nodes.values():
            if node.status == "refuted":
                continue
            if not any(state.ces[ce].q_id in was_open
                       for ce in node.ce_ids):
                continue
            standing = [ce_id for ce_id in node.ce_ids
                        if state.ces[ce_id].q_id in was_open
                        and V.is_standing(state, ce_id)]
            tray.append({"node_id": node.node_id,
                         "status": "carried_unresolved",
                         "ces": standing})
            tray_nodes.add(node.node_id)
        canvas = {
            "board_id": state.board_id,
            "x_title": state.x_title,
            "medium": state.medium,
            "status": "closed",
            "closed_seq": state.seq + 1,
            "active_node_id": state.active_node_id,
            "nodes": [
                {"node_id": n.node_id, "version": n.version,
                 "status": ("carried_unresolved"
                            if n.node_id in tray_nodes else n.status),
                 "text": n.text, "is_active": n.is_active,
                 "ce_ids": list(n.ce_ids)}
                for n in state.nodes.values()
            ],
            "ces": [
                {"ce_id": c.ce_id, "node_id": c.node_id, "shape": c.shape,
                 "q_id": c.q_id}
                for c in state.ces.values()
            ],
            "questions": [
                {"q_id": q.q_id, "kind": q.kind, "status": q.status,
                 "subject": q.subject, "outcome": q.outcome,
                 "opened_by": q.opened_by, "opened_seq": q.opened_seq,
                 "settled_seq": q.settled_seq}
                for q in state.questions.values()
            ],
            "carried_unresolved": tray,
        }
        return tray, canvas

    # -- read side (thin wrappers over board.verdicts) -----------------------

    def census(self, q_id: str) -> frozenset[str]:
        self._require_board()
        return V.census(self._state, q_id)

    def counted(self, q_id: str, handle_id: str) -> Ballot | None:
        self._require_board()
        return V.counted_ballot(self._state, q_id, handle_id)

    def standing_counts(self, ce_id: str) -> tuple[int, int]:
        self._require_board()
        if ce_id not in self._state.ces:
            raise UnknownCounterexample(f"unknown ce: {ce_id}")
        return V.standing_counts(self._state, ce_id)

    def is_standing(self, ce_id: str) -> bool:
        self._require_board()
        if ce_id not in self._state.ces:
            raise UnknownCounterexample(f"unknown ce: {ce_id}")
        return V.is_standing(self._state, ce_id)

    def is_refuted(self, ce_id_or_node_id: str) -> bool:
        """Node-level verdict; accepts either a node id or a CE id."""
        self._require_board()
        if ce_id_or_node_id in self._state.ces:
            node_id = self._state.ces[ce_id_or_node_id].node_id
        elif ce_id_or_node_id in self._state.nodes:
            node_id = ce_id_or_node_id
        else:
            raise UnknownNode(f"unknown node/ce: {ce_id_or_node_id}")
        return V.is_refuted(self._state, node_id)

    def q_status(self, q_id: str) -> tuple[str, str | None]:
        self._require_board()
        q = self._get_q(q_id)
        return q.status, q.outcome

    def is_closed(self) -> bool:
        self._require_board()
        return self._state.status == "closed"

    def governance_passed(self, q_id: str) -> str | None:
        self._require_board()
        return V.governance_passed(self._state, q_id)
