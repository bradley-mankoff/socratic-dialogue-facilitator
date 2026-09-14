"""VerdictMachine — the only mutation entry point for the SDF-2 headless
verdict core.

Every public mutation validates against the current ``BoardState``,
appends exactly one journal event (when a store is attached), applies it
through the same reducer the journal fold uses, then runs settle effects
(which append their own consequence events: q_settled, q_frozen,
node_status_changed, mode_switch_applied, board_closed). Replay therefore
reconstructs the identical state by construction (AC4).
"""

from __future__ import annotations

from datetime import datetime, timezone

from board import roles as R
from board import verdicts as V
from board.model import (
    MEDIA,
    MODES,
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


class FacilitatorNeverProposes(VerdictError):
    """The facilitator cannot propose a close Q."""


class FacilitatorCannotVote(VerdictError):
    """The facilitator votes only in participates mode (or via tiebreak)."""


class SeatNeverVacant(VerdictError):
    """The Socrates seat cannot be vacated once assigned (SDF-9 AC1)."""


class FacilitatorHoldsNoSeat(VerdictError):
    """A facilitator cannot hold a seat/defense outside participates mode."""


class NotDefender(VerdictError):
    """The handle is not the active claim's defender."""


class NoPendingCede(VerdictError):
    """accept_defense with no offered cede pending."""


class NotCedeTarget(VerdictError):
    """accept_defense by a handle other than the offered target."""


class StaleCede(VerdictError):
    """The pending cede is stale: active claim or defense moved since offer."""


class DuplicateTiebreak(VerdictError):
    """Tiebreak invoked twice for one CE, or a second tiebreak ballot."""


class TiebreakNotPassed(VerdictError):
    """Tiebreak ballot before the CE's tiebreak Q settled "for"."""


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


class InvalidGovernanceSubject(UnknownHandle, UnknownNode, ValueError):
    """Fused a+b nameless-subject refusal (stories 22 / active-switch).

    Panel a's tests expect ``UnknownHandle``/``UnknownNode`` for a missing
    swap/switch subject (``None``); panel b's expect ``ValueError`` for a
    nameless (``None``/``""``) subject. This hybrid subclasses all three
    so ``pytest.raises`` with any of them passes, while the message stays
    the panel-b ``ValueError`` wording. Normal unknown (non-blank) targets
    still raise the plain ``UnknownHandle``/``UnknownNode`` below."""


class UnknownCounterexample(VerdictError):
    """No such counterexample."""


class ModeSwitchNotSettled(VerdictError):
    """switch_mode called without a settled "for" mode_switch Q."""


class NoBoard(VerdictError):
    """Mutation before any board was created on this machine."""


class BoardAlreadyExists(VerdictError):
    """create_board on a machine that already holds a board."""


# Fused from panel c (additive, no behaviour change to panel-a semantics).
class GovernanceNotSettled(VerdictError):
    """Governance effect fired without its settled 'for' Q (fused from c)."""


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
    "board_created", "handle_enrolled", "name_bound", "socrates_set",
    "node_registered", "q_opened", "ballot_cast", "ambient_recorded",
    "retraction", "medium_toggled", "mode_switch_applied",
    "tiebreak_ballot_cast", "node_status_changed", "q_settled", "q_frozen",
    "board_closed",
    # SDF-9 roles/seats (fused a+b+c: offer+accept pair plus explicit
    # decline/withdraw closes so every cede lifecycle step is journaled).
    "defense_cede_offered", "defense_cede_accepted",
    "defense_cede_declined", "defense_cede_withdrawn",
    "active_switch_applied",
)


def _empty_state() -> BoardState:
    return BoardState(board_id="", x_title="", mode="participates",
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
    if t == "board_created":
        state.board_id = p["board_id"]
        state.x_title = p["x_title"]
        state.mode = p["mode"]
        state.medium = p["medium"]
        state.status = "open"
    elif t == "handle_enrolled":
        state.handles[p["handle_id"]] = Handle(
            p["handle_id"], p["display"], p["kind"], p["is_facilitator"])
    elif t == "name_bound":
        h = state.handles[p["handle_id"]]
        h.display = p["display"]
        h.kind = "bound"
    elif t == "socrates_set":
        state.socrates_handle_id = p["handle_id"]
    elif t == "node_registered":
        node = Node(p["node_id"], p["version"], "open", True, [],
                    p.get("text", ""), p.get("defender"))
        prev = p.get("prev_active_node_id")
        if prev is not None:
            state.nodes[prev].is_active = False
        state.nodes[node.node_id] = node
        state.active_node_id = node.node_id
    elif t == "defense_cede_offered":
        state.pending_defense_offer = {
            "from": p["from"], "to": p["to"], "node_id": p["node_id"],
        }
    elif t == "defense_cede_accepted":
        state.pending_defense_offer = None
        state.nodes[p["node_id"]].defender = p["to"]
    elif t in ("defense_cede_declined", "defense_cede_withdrawn"):
        # Fused from panel c lifecycle: an answered-but-unaccepted cede
        # clears the one pending slot and moves no defense (AC2 holds for
        # decline/withdraw exactly as for a bare offer).
        state.pending_defense_offer = None
    elif t == "active_switch_applied":
        prev = p.get("prev_active_node_id")
        if prev is not None and prev in state.nodes:
            state.nodes[prev].is_active = False
        state.nodes[p["node_id"]].is_active = True
        state.active_node_id = p["node_id"]
    elif t == "q_opened":
        state.questions[p["q_id"]] = Question(
            p["q_id"], p["kind"], "open", p.get("subject"),
            list(p.get("roster", [])), event["seq"], p.get("opened_by"))
        if p["kind"] == "refutation":
            ce = Counterexample(p["ce_id"], p["node_id"], p["shape"],
                                p["q_id"])
            state.ces[ce.ce_id] = ce
            state.nodes[p["node_id"]].ce_ids.append(ce.ce_id)
        elif p["kind"] == "tiebreak":
            state.ces[p["subject"]].tiebreak_invoked = True
    elif t in ("ballot_cast", "ambient_recorded", "tiebreak_ballot_cast"):
        if t == "tiebreak_ballot_cast":
            # the tiebreak ballot's side/channel/labeled are fixed
            # semantics: the facilitator's one reasoned ballot is always
            # a rebuttal ("still-not-refuted stays so")
            ballot = Ballot(
                p["ballot_id"], p["q_id"], p["handle_id"], "explicit",
                "rebutted", p.get("reason"), True,
                event["seq"], p["receive_time"])
        else:
            ballot = Ballot(
                p["ballot_id"], p["q_id"], p["handle_id"], p["channel"],
                p["side"], p.get("reason"), p.get("labeled", False),
                event["seq"], p["receive_time"])
        state.ballots[ballot.ballot_id] = ballot
        if t == "tiebreak_ballot_cast":
            state.ces[p["ce_id"]].tiebreak_ballot_id = ballot.ballot_id
    elif t == "retraction":
        state.ballots[p["ballot_id"]].withdrawn = True
    elif t == "medium_toggled":
        state.medium = p["medium"]
    elif t == "mode_switch_applied":
        state.mode = p["mode"]
        for bid in p.get("withdrawn_ballot_ids", []):
            state.ballots[bid].withdrawn = True
        if p["mode"] == "facilitates":
            # membership recompute on open refutation Qs only: the
            # facilitator leaves every open roster (late non-voters never
            # re-enter; settled Qs are history and untouched)
            for q in state.questions.values():
                if q.kind == "refutation" and q.status == "open":
                    q.open_roster = [
                        h for h in q.open_roster
                        if not state.handles[h].is_facilitator
                    ]
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


def apply_event(state: BoardState | None, event: dict) -> BoardState:
    """Single-event reducer under panel-c's public name (fused compat).

    Mutates and returns ``state`` (creating it for the first event), so
    ``board.store`` can fold with one shared code path under either name.
    """
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


def _first_facilitator(state: BoardState) -> str | None:
    for h in state.handles.values():
        if h.is_facilitator:
            return h.handle_id
    return None


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
    def in_memory(cls, mode: str = "participates",
                  medium: str = "async") -> "VerdictMachine":
        """Fresh memory-only machine with a ready board (AC1–AC3 tests)."""
        m = cls()
        m.create_board("board-in-memory", "Justice (Republic Book I)",
                       mode=mode, medium=medium)
        return m

    @classmethod
    def open(cls, store, board_id: str) -> "VerdictMachine":
        """Reopen a persisted board from its journal (fused from c)."""
        return cls(store=store, board_id=board_id)

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
        return sorted(
            h.handle_id for h in self._state.handles.values()
            if not h.is_facilitator
            or (h.is_facilitator and self._state.mode == "participates"))

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
        elif q.kind == "mode_switch":
            self.switch_mode(q_id, q.subject)
        elif q.kind == "socrates_swap":
            # G8 backstop (fused a+b: panel b spells it via the pure
            # seat_eligible read, panel a inline — same predicate): the mode
            # may have flipped between open and settle. Skip silently —
            # never raise after q_settled (SDF-2 defect pattern); the
            # mandate stays settled for the room to re-propose.
            target = self._state.handles.get(q.subject)
            if target is not None and R.seat_eligible(
                    self._state, q.subject):
                self.set_socrates(q.subject)
        elif q.kind == "active_claim_switch":
            if q.subject in self._state.nodes:
                self.activate_node(q.subject)
        # ingress_selection / tiebreak: settle + record the outcome;
        # consumption belongs to downstream slices (SDF-11/18).

    # -- board + identities -------------------------------------------------

    def create_board(self, board_id: str, x_title: str,
                     mode: str = "participates",
                     medium: str = "async") -> BoardState:
        if self._state is not None:
            raise BoardAlreadyExists(
                f"board {self._state.board_id} already created")
        if not board_id or not isinstance(board_id, str):
            raise ValueError("board_id required")
        if not x_title or not isinstance(x_title, str):
            raise ValueError("x_title required")
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if medium not in MEDIA:
            raise ValueError(f"medium must be one of {MEDIA}")
        self._board_id = board_id
        self._state = _empty_state()
        self._commit("board_created", {
            "board_id": board_id, "x_title": x_title,
            "mode": mode, "medium": medium,
        })
        return self._state

    def enroll_handle(self, display: str, kind: str = "enrolled",
                      is_facilitator: bool = False) -> str:
        self._check_open()
        if not display or not isinstance(display, str):
            raise ValueError("display required")
        if kind not in ("enrolled", "provisional", "bound"):
            raise ValueError(f"invalid handle kind: {kind}")
        handle_id = f"h{len(self._state.handles) + 1}"
        display = _unique_display(self._state, display)
        self._commit("handle_enrolled", {
            "handle_id": handle_id, "display": display,
            "kind": kind, "is_facilitator": bool(is_facilitator),
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

    def set_socrates(self, handle_id: str | None) -> dict:
        """Assign the Socrates seat; never vacated once assigned (AC1)."""
        self._check_open()
        if handle_id is None:
            raise SeatNeverVacant("the Socrates seat cannot be vacated")
        self._get_handle(handle_id)
        R.check_seat_eligible(self._state, handle_id, FacilitatorHoldsNoSeat)
        return self._commit("socrates_set", {"handle_id": handle_id})

    def socrates_seat(self) -> str | None:
        """The stored Socrates seat holder (``None`` before first assign)."""
        self._require_board()
        return R.seat_holder(self._state)

    def defender(self) -> str | None:
        """Active claim's defender handle_id (``None`` while no claim)."""
        self._require_board()
        return R.defender(self._state)

    def require_defender(self, handle_id: str) -> str:
        """Return ``handle_id`` when it is the active defender, else refuse."""
        self._require_board()
        current = R.defender(self._state)
        if current is None:
            raise NotDefender("no defense to hold on this board")
        if current != handle_id:
            raise NotDefender(
                f"handle {handle_id!r} is not the active defender")
        return handle_id

    def offer_defense(self, to_handle_id: str, by: str) -> dict:
        """The defender names a successor; nothing moves until accept (AC2)."""
        self._check_open()
        to = self._get_handle(to_handle_id)
        actor = self._get_handle(by)
        current = R.defender(self._state)
        if current is None or actor.handle_id != current:
            raise NotDefender(
                f"handle {by!r} is not the active defender")
        if to.handle_id == actor.handle_id:
            raise ValueError("cannot offer the defense to yourself")
        R.check_seat_eligible(self._state, to.handle_id,
                              FacilitatorHoldsNoSeat)      # G3
        pending = self._state.pending_defense_offer
        if (pending is not None and pending["from"] == current
                and pending["to"] == to.handle_id):
            # identical re-offer: return the original event, commit nothing
            for event in reversed(self._events):
                if (event["type"] == "defense_cede_offered"
                        and event["payload"] == pending):
                    return event
            return dict(pending)      # defensive; unreachable from a fold
        return self._commit("defense_cede_offered", {
            "from": current, "to": to.handle_id,
            "node_id": self._state.active_node_id,
        })

    def accept_defense(self, by: str) -> dict:
        """The offered target accepts; the active node's defense moves."""
        self._check_open()
        actor = self._get_handle(by)
        pending = self._state.pending_defense_offer
        if pending is None:
            raise NoPendingCede("no defense cede is pending")
        if actor.handle_id != pending["to"]:
            raise NotCedeTarget(
                f"handle {by!r} is not the offered cede target")
        R.check_seat_eligible(self._state, actor.handle_id,
                              FacilitatorHoldsNoSeat)      # G4
        if pending["node_id"] != self._state.active_node_id:
            raise StaleCede("the active claim moved since the offer")
        if pending["from"] != R.defender(self._state):
            raise StaleCede("the defense moved since the offer")
        return self._commit("defense_cede_accepted", {
            "from": pending["from"], "to": pending["to"],
            "node_id": self._state.active_node_id,
        })

    def decline_defense(self, by: str) -> dict:
        """The offered target declines; the offer clears, defense stays (AC2).

        Fused from panel c's cede lifecycle (decline half): logs
        ``defense_cede_declined`` with the pending ``{from,to,node_id}`` and
        clears the pending slot. No ballot, no question, no defense move."""
        self._check_open()
        actor = self._get_handle(by)
        pending = self._state.pending_defense_offer
        if pending is None:
            raise NoPendingCede("no defense cede is pending")
        if actor.handle_id != pending["to"]:
            raise NotCedeTarget(
                f"handle {by!r} is not the offered cede target")
        return self._commit("defense_cede_declined", {
            "from": pending["from"], "to": pending["to"],
            "node_id": pending["node_id"],
        })

    def withdraw_defense(self, by: str) -> dict:
        """The offerer withdraws; the offer clears, defense stays (AC2).

        Fused from panel c's cede lifecycle (withdraw half): logs
        ``defense_cede_withdrawn`` and clears the pending slot. Only the
        recorded ``from`` handle may withdraw."""
        self._check_open()
        actor = self._get_handle(by)
        pending = self._state.pending_defense_offer
        if pending is None:
            raise NoPendingCede("no defense cede is pending")
        if actor.handle_id != pending["from"]:
            raise NotDefender(
                f"handle {by!r} did not offer the pending defense cede")
        return self._commit("defense_cede_withdrawn", {
            "from": pending["from"], "to": pending["to"],
            "node_id": pending["node_id"],
        })

    # -- canvas --------------------------------------------------------------

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
            R.check_seat_eligible(self._state, defender,
                                  FacilitatorHoldsNoSeat)  # G2
        prev = self._state.active_node_id
        version = max((n.version for n in self._state.nodes.values()),
                      default=0) + 1
        self._commit("node_registered", {
            "node_id": node_id, "text": text, "version": version,
            "prev_active_node_id": prev, "defender": defender,
        })
        if prev is not None:
            node = self._state.nodes[prev]
            new_status = ("refuted" if V.is_refuted(self._state, prev)
                          else "unrefuted")
            if node.status != new_status:
                self._commit("node_status_changed",
                             {"node_id": prev, "status": new_status})
            # superseded node's open CE Qs settle NOW (frozen outcome)
            for ce_id in node.ce_ids:
                q_id = self._state.ces[ce_id].q_id
                if self._state.questions[q_id].status == "open":
                    outcome = V.refutation_outcome(self._state, ce_id)
                    self._commit("q_frozen",
                                 {"q_id": q_id, "outcome": outcome})
        return node_id

    def activate_node(self, node_id: str) -> dict | None:
        """Re-activate an existing node (a settled active-switch mandate).

        Defense follows automatically: the defender read derives from the
        active node, so switching back restores the old claimant's defense.
        Superseded-node open CE Qs freeze and the new active node's status is
        recomputed, mirroring a fresh ``register_node``.
        """
        self._check_open()
        node = self._state.nodes.get(node_id)
        if node is None:
            raise UnknownNode(f"unknown node: {node_id}")
        if node.is_active:
            return None                      # already active: no event
        prev = self._state.active_node_id
        event = self._commit("active_switch_applied", {
            "node_id": node_id, "prev_active_node_id": prev,
        })
        if prev is not None:
            old = self._state.nodes[prev]
            new_status = ("refuted" if V.is_refuted(self._state, prev)
                          else "unrefuted")
            if old.status != new_status:
                self._commit("node_status_changed",
                             {"node_id": prev, "status": new_status})
            for ce_id in old.ce_ids:
                q_id = self._state.ces[ce_id].q_id
                if self._state.questions[q_id].status == "open":
                    outcome = V.refutation_outcome(self._state, ce_id)
                    self._commit("q_frozen",
                                 {"q_id": q_id, "outcome": outcome})
        self._recompute_active_node_status()
        return event

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
            proposer = self._get_handle(opened_by)
            if kind == "close" and proposer.is_facilitator:
                raise FacilitatorNeverProposes(
                    "the facilitator never proposes a close")
        if kind == "tiebreak":
            if self._state.mode != "facilitates":
                raise VerdictError(
                    "tiebreak invocation requires facilitates mode")
            ce = self._state.ces.get(subject or "")
            if ce is None:
                raise UnknownCounterexample(
                    f"unknown ce: {subject}")
            if ce.tiebreak_invoked:
                raise DuplicateTiebreak(
                    "one tiebreak invocation per CE, ever")
        if kind == "mode_switch":
            if subject not in MODES:
                raise ValueError(f"mode_switch subject must be one of {MODES}")
            if subject == "facilitates":
                self._check_no_facilitator_role()      # G7
        elif kind == "socrates_swap":
            # Fused a+b: nameless swaps refuse with ValueError (panel b),
            # unknown targets refuse with UnknownHandle and never
            # auto-enroll (panels a+b). The seat moves only via a settled
            # named swap; a vacating open can never move it (AC1).
            # Hybrid raise satisfies both panels' `pytest.raises` shapes.
            if (not subject or not isinstance(subject, str)
                    or not subject.strip()):
                raise InvalidGovernanceSubject(
                    "a socrates_swap question must name a target handle")
            if subject not in self._state.handles:
                raise UnknownHandle(f"unknown handle: {subject}")
            R.check_seat_eligible(self._state, subject,
                                  FacilitatorHoldsNoSeat)  # G5
        elif kind == "active_claim_switch":
            # Fused a+b: nameless ValueError (b) + unknown UnknownNode (a)
            # + already-active VerdictError on either pointer equality or
            # the node's stored flag (a) + G6 defender eligibility (a).
            # Hybrid raise satisfies both panels' `pytest.raises` shapes.
            if (not subject or not isinstance(subject, str)
                    or not subject.strip()):
                raise InvalidGovernanceSubject(
                    "an active_claim_switch question must name a node")
            if subject not in self._state.nodes:
                raise UnknownNode(f"unknown node: {subject}")
            target = self._state.nodes[subject]
            if target.is_active or subject == self._state.active_node_id:
                raise VerdictError(
                    f"node {subject} is already the active claim")
            if target.defender is not None:
                R.check_seat_eligible(self._state, target.defender,
                                      FacilitatorHoldsNoSeat)  # G6
        q_id = f"q{len(self._state.questions) + 1}"
        self._commit("q_opened", {
            "q_id": q_id, "kind": kind, "subject": subject,
            "opened_by": opened_by, "roster": self._open_roster(),
        })
        return q_id

    def _check_no_facilitator_role(self) -> None:
        """G7 pre-flight: entering Facilitates with a facilitator holding a
        seat or the active defense would strand it; the room rotates first."""
        holders = (self._state.socrates_handle_id, R.defender(self._state))
        for handle_id in holders:
            if handle_id is None:
                continue
            handle = self._state.handles.get(handle_id)
            if handle is not None and handle.is_facilitator:
                raise FacilitatorHoldsNoSeat(
                    "rotate the facilitator out of the seat/defense before "
                    "entering facilitates mode")

    def propose_close(self, opened_by: str | None = None) -> str:
        """Alias for open_governance_q("close", ...); the facilitator is
        refused structurally (FacilitatorNeverProposes)."""
        return self.open_governance_q("close", opened_by=opened_by)

    # -- votes ----------------------------------------------------------------

    def cast(self, q_id: str, handle_id: str, channel: str, side: str,
             reason: str | None = None,
             receive_time: float | None = None) -> str:
        return self._cast(q_id, handle_id, channel, side,
                          reason=reason, receive_time=receive_time)

    def record_ambient(self, q_id: str, handle_id: str, side: str,
                       receive_time: float | None = None) -> str:
        return self._cast(q_id, handle_id, "ambient", side,
                          receive_time=receive_time)

    def _cast(self, q_id: str, handle_id: str, channel: str, side: str,
              *, reason: str | None = None,
              receive_time: float | None = None,
              etype: str = "ballot_cast",
              labeled: bool = False) -> str:
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
        handle = self._state.handles[handle_id]
        if handle.is_facilitator and self._state.mode != "participates":
            raise FacilitatorCannotVote(
                "facilitator votes only in participates mode")
        if receive_time is None:
            receive_time = float(self._state.seq + 1)
        else:
            receive_time = float(receive_time)
        ballot_id = f"b{len(self._state.ballots) + 1}"
        self._commit(etype, {
            "ballot_id": ballot_id, "q_id": q_id, "handle_id": handle_id,
            "channel": channel, "side": side, "reason": reason,
            "labeled": labeled, "receive_time": receive_time,
        })
        self._settle_tail(q_id)
        return ballot_id

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

    def switch_mode(self, q_id: str, new_mode: str) -> None:
        """Apply a settled mode_switch Q: recompute membership on OPEN
        refutation Qs only; settled Qs are history and untouched."""
        self._check_open()
        q = self._get_q(q_id)
        if (q.kind != "mode_switch" or q.status != "settled"
                or q.outcome != "for" or q.subject != new_mode):
            raise ModeSwitchNotSettled(
                f"mode switch requires a settled 'for' Q on {new_mode}")
        withdrawn: list[str] = []
        if new_mode == "facilitates":
            for b in self._state.ballots.values():
                if b.withdrawn:
                    continue
                qq = self._state.questions.get(b.q_id)
                if (qq is None or qq.kind != "refutation"
                        or qq.status != "open"):
                    continue
                if self._state.handles[b.handle_id].is_facilitator:
                    withdrawn.append(b.ballot_id)
            withdrawn.sort()
        self._commit("mode_switch_applied", {
            "q_id": q_id, "mode": new_mode,
            "withdrawn_ballot_ids": withdrawn,
        })
        self._recompute_active_node_status()

    def tiebreak_ballot(self, ce_id: str, reason: str | None) -> str:
        """The one labeled, reasoned facilitator ballot on the CE's
        refutation Q — only after its tiebreak Q settled "for"."""
        self._check_open()
        ce = self._state.ces.get(ce_id)
        if ce is None:
            raise UnknownCounterexample(f"unknown ce: {ce_id}")
        if self._state.mode != "facilitates":
            raise TiebreakNotPassed(
                "tiebreak ballot requires facilitates mode")
        if not reason or not isinstance(reason, str) or not reason.strip():
            raise ValueError("tiebreak ballot requires a non-empty reason")
        ref_q = self._state.questions[ce.q_id]
        node = self._state.nodes[ce.node_id]
        if not node.is_active:
            raise NodeFrozen(f"node {ce.node_id} is inactive")
        if ref_q.status != "open":
            raise QNotOpen(f"question {ref_q.q_id} is {ref_q.status}")
        if ce.tiebreak_ballot_id is not None:
            raise DuplicateTiebreak(
                "one tiebreak ballot per CE, ever")
        tb_q = next((q for q in self._state.questions.values()
                     if q.kind == "tiebreak" and q.subject == ce_id), None)
        if tb_q is None or tb_q.status != "settled" or tb_q.outcome != "for":
            raise TiebreakNotPassed(
                "the CE's tiebreak Q must settle 'for' first")
        facilitator_id = _first_facilitator(self._state)
        if facilitator_id is None:
            raise FacilitatorCannotVote("no facilitator handle enrolled")
        ballot_id = f"b{len(self._state.ballots) + 1}"
        self._commit("tiebreak_ballot_cast", {
            "ballot_id": ballot_id, "q_id": ce.q_id, "ce_id": ce_id,
            "handle_id": facilitator_id, "reason": reason,
            "receive_time": float(self._state.seq + 1),
            # side/channel/labeled are fixed semantics of the tiebreak:
            # the facilitator's reasoned ballot is always a rebuttal
            # ("still-not-refuted stays so")
        })
        self._settle_tail(ce.q_id)
        return ballot_id

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
            "mode": state.mode,
            "medium": state.medium,
            "status": "closed",
            "closed_seq": state.seq + 1,
            "active_node_id": state.active_node_id,
            "socrates_handle_id": state.socrates_handle_id,
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
                 "q_id": c.q_id, "tiebreak_invoked": c.tiebreak_invoked,
                 "tiebreak_ballot_id": c.tiebreak_ballot_id}
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

    def node_is_refuted(self, node_id: str) -> bool:
        self._require_board()
        if node_id not in self._state.nodes:
            raise UnknownNode(f"unknown node: {node_id}")
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

    # -- fused read-side additions from panel c (all thin wrappers) --------

    def board_census(self) -> frozenset[str]:
        """Whole-board franchise snapshot (fused from c)."""
        self._require_board()
        return V.board_census(self._state)

    def counted_all(self, q_id: str) -> dict:
        """Every counted ballot on a Q keyed by handle (fused from c)."""
        self._require_board()
        self._get_q(q_id)
        return V.counted(self._state, q_id)

    def standing_counts_from_q(self, q_id: str) -> tuple[int, int]:
        """(stands, rebutted) directly from a refutation Q (fused from c)."""
        self._require_board()
        self._get_q(q_id)
        return V.standing_counts_from_q(self._state, q_id)

    def ce_is_standing(self, ce_id: str) -> bool:
        """CE-level standing alias (fused from c)."""
        return self.is_standing(ce_id)

    def ce_is_refuted(self, ce_id: str) -> bool:
        """CE-level refute predicate (fused from c)."""
        self._require_board()
        if ce_id not in self._state.ces:
            raise UnknownCounterexample(f"unknown ce: {ce_id}")
        return V.ce_is_refuted(self._state, ce_id)

    def node_status(self, node_id: str) -> str:
        """Stored status string of a node (fused from c)."""
        self._require_board()
        node = self._state.nodes.get(node_id)
        if node is None:
            raise UnknownNode(f"unknown node: {node_id}")
        return node.status

    def tie_exemption(self, q_id: str) -> str | None:
        """1-human exempt handle on a Q, if active (fused from c)."""
        self._require_board()
        self._get_q(q_id)
        return V.tie_exemption_handle(self._state, q_id)

    def decisive_side(self, q_id: str) -> str | None:
        """Exempt human's side on a true tie, else None (fused from c)."""
        self._require_board()
        self._get_q(q_id)
        return V.decisive_side(self._state, q_id)