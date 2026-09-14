"""BoardService — SDF-5 board operations end to end + SDF-6 scrutiny.

The public API: open a board on ``(X, label)``, pick its mode, pull/serve
canonical definitions, claim one (source-tagged) or author an original,
revise the active claim into a new version node — then allege labeled
counterexamples, ingest explicit/ambient ballots, retract ambient ones,
run tiebreak-invoke governance, and read the live scoreboard.

Division of authority (downstream SDF-7/10/14/18 depend on this):

* **Verdict state** is owned by ``board.machine.VerdictMachine`` and its
  per-board ``journal.jsonl``. This module is the *only* caller of
  ``register_node`` in the slice and never writes a verdict event itself;
  the SDF-6 scrutiny methods stay thin: resolve → one machine mutator →
  shape the result → ``sync_registry`` on the four verdict-affecting paths
  (``cast_vote``, ``record_ambient_vote``, ``retract_vote``,
  ``cast_tiebreak_ballot``) and never on reads or on ``allege``/
  ``invoke_tiebreak`` (they cannot move a mirror).
* **Provenance and the revision (tray) event** live in the ``meta.jsonl``
  sidecar (:class:`server.store.MetaLog`). The machine never reads it and
  this module never appends to the journal — ``board.machine._apply`` raises
  on unknown event types, so a foreign line would break replay forever.
* **Canonicals** belong to the SDF-3 chain, cached per normalized X and
  shared by every board on that X (issue 02: "never re-pulled mid-dialogue").

Activation is not implemented here on purpose: ``register_node`` already
makes the new node the single active one and freezes the superseded node's
open questions, so the first claim auto-activates and every revision is
append-only by construction (AC2, AC3).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import board.verdicts as V
from board.machine import BoardClosed, VerdictMachine
from board.model import MEDIA, MODES, SHAPES, BoardState
from board.store import JsonlStore
from dictionary.chain import DictionaryChain, build_default_chain
from dictionary.normalize import normalize_x
from server.errors import (
    BlankClaim,
    ClaimAlreadyActive,
    EmptyCanonicals,
    NoActiveClaim,
    NoCanonicals,
    NotActiveNode,
    UnknownBoard,
    UnknownCounterexample,
    UnknownHandle,
    UnknownNode,
    UnknownQuestion,
    UnknownSense,
)
from server.model import (
    CLAIM_RECORDED,
    CLAIM_REVISED,
    TRAY_NAME,
    VOTE_EVENT_TYPES,
    AllegationResult,
    BoardRecord,
    ClaimResult,
    OpenResult,
    TiebreakResult,
    VoteResult,
    canonical_provenance,
    now_iso,
    original_provenance,
)
from server.store import (
    DEFAULT_ROOT,
    BoardRegistry,
    CanonicalStore,
    MetaLog,
    creation_key,
    registry_path,
)
from server.views import board_view, boards_view, scoreboard_view


class BoardService:
    """One object per data root; every board under that root is reachable."""

    def __init__(self, root: Path | str = DEFAULT_ROOT, *,
                 chain: DictionaryChain | None = None,
                 clock: Callable[[], str] | None = None) -> None:
        self.root = Path(root)
        self.chain = chain
        self._clock = clock or now_iso
        self.journals = JsonlStore(self.root)
        self.registry = BoardRegistry(registry_path(self.root))
        self.canonical_store = CanonicalStore(self.root,
                                              chain=self._chain_or_get)
        self.meta = MetaLog(self.root)
        self._machines: dict[str, VerdictMachine] = {}

    @classmethod
    def open(cls, home: Path | str = Path("store"),
             chain: DictionaryChain | None = None,
             clock: Callable[[], str] | None = None) -> "BoardService":
        """Re-open the data home; every board and snapshot comes from disk."""
        return cls(home, chain=chain, clock=clock)

    # -- canonical chain (lazy: never built at import/construct) -----------

    def _chain(self) -> DictionaryChain:
        if self.chain is None:
            self.chain = build_default_chain()
        return self.chain

    def _chain_or_get(self) -> DictionaryChain:
        return self._chain()

    # -- boards -------------------------------------------------------------

    def open_board(self, x: str, label: str | None = None, *,
                   mode: str = "participates", medium: str = "async",
                   pull_canonicals: bool = True) -> OpenResult:
        """Get-or-create the board keyed by ``(normalize_x(X), label)``.

        Validation and the canonical pull happen *before* any write, so a bad
        argument or a dead dictionary leaves no half-open board.
        """
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if medium not in MEDIA:
            raise ValueError(f"medium must be one of {MEDIA}")
        if not x or not isinstance(x, str) or not normalize_x(x):
            raise ValueError("x must contain a non-whitespace character")
        if label is not None and (not isinstance(label, str)
                                  or not label.strip()):
            raise ValueError("label must be a non-blank string")

        xn = normalize_x(x)
        if label is None:
            label = self.registry.next_label(xn)
        else:
            existing = self.registry.get(xn, label)
            if existing is not None:      # GET path: mode/medium are ignored
                return OpenResult(
                    record=existing, created=False,
                    view=self.view(existing.board_id))

        if pull_canonicals:
            # first write wins per X; a second same-X board costs zero calls
            self.canonical_store.get(xn)

        record = self.registry.reserve(x=x, x_title=str(x).strip(),
                                       label=label, mode=mode, medium=medium)
        machine = VerdictMachine(self.journals, record.board_id)
        machine.create_board(record.board_id, str(x).strip(), mode, medium)
        self._machines[record.board_id] = machine
        return OpenResult(record=record, created=True,
                          view=self.view(record.board_id))

    def board(self, board_id: str) -> BoardRecord:
        """Registry row for ``board_id`` (raises :class:`UnknownBoard`)."""
        record = self.registry.by_id(board_id)
        if record is None:
            raise UnknownBoard(f"unknown board: {board_id}")
        return record

    def list_boards(self, x: str | None = None) -> list[BoardRecord]:
        """All boards (created order), or just the ones on ``x``."""
        if x is None:
            return sorted(self.registry.boards.values(), key=creation_key)
        return self.registry.boards_for(x)

    def machine(self, board_id: str) -> VerdictMachine:
        """The board's SDF-2 machine — the escape hatch for SDF-6 votes."""
        self.board(board_id)
        cached = self._machines.get(board_id)
        if cached is not None:
            return cached
        machine = VerdictMachine(self.journals, board_id)
        if machine.state is None:
            raise UnknownBoard(f"board {board_id} has no journal")
        self._machines[board_id] = machine
        return machine

    def state(self, board_id: str) -> BoardState:
        return self.machine(board_id).state

    def sync_registry(self, board_id: str) -> BoardRecord:
        """Refresh the registry mirrors from live machine state.

        Call after mode/medium/close effects (the SDF-6/8 contract). Never on
        a read path — :meth:`view` reads the machine directly.
        """
        state = self.machine(board_id).state
        return self.registry.mark(board_id, mode=state.mode,
                                  medium=state.medium, status=state.status)

    # -- canonicals ---------------------------------------------------------

    def canonicals(self, board_id: str) -> dict | None:
        """Cached snapshot for this board's X; ``None`` when the pull was
        deferred. Reads the shared per-X cache only — never pulls."""
        record = self.board(board_id)
        return self.canonical_store.cached(record.x_norm)

    # -- claims --------------------------------------------------------------

    def claim_canonical(self, board_id: str, sense_id: str | None = None, *,
                        claimant_display: str) -> ClaimResult:
        """Claim a cached canonical definition, verbatim and source-tagged."""
        return self._register_claim(board_id, None, kind="canonical",
                                    sense_id=sense_id,
                                    claimant_display=claimant_display)

    def claim_original(self, board_id: str, text: str, *,
                       claimant_display: str) -> ClaimResult:
        """Author an original claim (no source tag, no cites)."""
        return self._register_claim(board_id, text, kind="original",
                                    claimant_display=claimant_display)

    def revise(self, board_id: str, text: str, *,
               claimant_display: str,
               in_response_to: str | None = None) -> ClaimResult:
        """Supersede the active claim with a new version node (AC3).

        History is never edited: the machine mints a fresh node, freezes the
        superseded node's open counterexample questions, and this call records
        the ``carried_unvoted`` event SDF-7 folds into a tray.
        """
        return self._register_claim(board_id, text, kind="original",
                                    claimant_display=claimant_display,
                                    in_response_to=in_response_to,
                                    revision=True)

    # -- provenance / ops log -------------------------------------------------

    def read_events(self, board_id: str,
                    etype: str | None = None) -> list[dict]:
        """Sidecar operation events for a board (``claim_recorded``/``..._revised``)."""
        self.board(board_id)
        return self.meta.read_events(board_id, etype)

    def provenance_map(self, board_id: str) -> dict[str, dict]:
        """``node_id -> provenance`` for every claim on this board."""
        mapping: dict[str, dict] = {}
        for event in self.read_events(board_id, CLAIM_RECORDED):
            payload = event.get("payload") or {}
            node_id = payload.get("node_id")
            provenance = payload.get("provenance")
            if node_id and provenance:
                mapping[node_id] = dict(provenance)
        return mapping

    def provenance(self, board_id: str, node_id: str) -> dict | None:
        return self.provenance_map(board_id).get(node_id)

    # -- views -----------------------------------------------------------------

    def view(self, board_id: str) -> dict:
        """JSON-able whole-board view (SDF-10's payload)."""
        record = self.board(board_id)
        machine = self.machine(board_id)
        snapshot = self.canonical_store.cached(record.x_norm)
        return board_view(
            record, machine.state, self.provenance_map(board_id), snapshot,
            shared_cache=len(self.registry.boards_for(record.x_norm)) > 1)

    def boards_list(self, x: str | None = None) -> list[dict]:
        return boards_view(self.list_boards(x))

    # -- scrutiny API (SDF-6): allege CEs, ingest votes, render scores ------

    def allege(self, board_id: str, shape: str, *, node_id: str | None = None,
               by_display: str | None = None,
               handle_id: str | None = None) -> AllegationResult:
        """Attach a labeled counterexample (``"3a"`` IS-X-but-fails or
        ``"3b"`` fits-but-NOT-X) to a claim node; the CE and its refutation
        question are 1:1 and the ballot opens immediately (AC1, story 15).

        Target resolution happens BEFORE any handle enrollment: default is
        the active claim, ``node_id`` names an explicit target, a claimless
        board is :class:`NoActiveClaim` and an unknown or superseded node is
        refused (unknown → :class:`UnknownNode`, inactive →
        :class:`NotActiveNode`). The alleger may be anonymous; a display is
        resolved once or enrolled. No ``sync_registry`` (opening a CE cannot
        move a mirror) and no sidecar write (claim events only).
        """
        self.board(board_id)
        machine = self.machine(board_id)
        state = machine.state
        if shape not in SHAPES:
            raise ValueError(f"shape must be one of {SHAPES}")
        target = node_id if node_id is not None else state.active_node_id
        if target is None:
            raise NoActiveClaim(
                f"board {board_id} has no active claim to allege against")
        if target not in state.nodes:
            raise UnknownNode(f"unknown node: {target}")
        if not state.nodes[target].is_active:
            raise NotActiveNode(
                f"node {target} is not the active claim; history is frozen")
        handle = self._resolve_handle(machine, handle_id, by_display,
                                      required=False)
        ce_id, q_id = machine.open_refutation_q(target, shape, opened_by=handle)
        return AllegationResult(
            board_id=board_id, node_id=target, ce_id=ce_id, q_id=q_id,
            shape=shape, opened_by=handle,
            opened_seq=machine.state.questions[q_id].opened_seq,
        )

    def cast_vote(self, board_id: str, q_id: str, side: str, *,
                  by_display: str | None = None,
                  handle_id: str | None = None, reason: str | None = None,
                  receive_time: float | None = None) -> VoteResult:
        """One explicit ballot through the machine (stories 16, 18, 21).

        Sides are machine vocabulary (``stands|rebutted`` on refutation Qs,
        ``for|against`` on governance Qs) and are never validated here. The
        counted ballot is the latest explicit by ``(receive_time, seq)``;
        re-voting is legal and latest-counts. ``refuted`` is the live node
        verdict *after* this vote — refutation Qs never settle."""
        return self._ingest_vote(
            board_id, q_id, "explicit", side, by_display=by_display,
            handle_id=handle_id, reason=reason, receive_time=receive_time)

    def record_ambient_vote(self, board_id: str, q_id: str, side: str, *,
                            by_display: str | None = None,
                            handle_id: str | None = None,
                            receive_time: float | None = None) -> VoteResult:
        """One ambient hook call per vote utterance, transcript order
        (SDF-14 contract, story 17).

        ``receive_time`` is the caller's transcript clock; omit it only for
        "now" (the machine defaults to ``seq + 1``). The service never
        reorders, buffers or drops; explicit ballots outrank ambient ones in
        both arrival orders (machine-owned precedence)."""
        return self._ingest_vote(board_id, q_id, "ambient", side,
                                 by_display=by_display, handle_id=handle_id,
                                 receive_time=receive_time)

    def retract_vote(self, board_id: str, q_id: str, *,
                     by_display: str | None = None,
                     handle_id: str | None = None) -> dict:
        """Ambient-only retraction (story 17).

        Withdraws the handle's counted ambient ballot so the older ambient
        (if any) resurfaces; an explicit ballot is never demoted, so
        retracting an explicit-only handle or nothing is a no-op with
        ``had_effect=False`` — changing an explicit vote means casting a new
        one. Frozen questions refuse with :class:`QNotOpen`.
        """
        self.board(board_id)
        machine = self.machine(board_id)
        state = machine.state
        if q_id not in state.questions:
            raise UnknownQuestion(f"unknown question: {q_id}")
        handle = self._resolve_handle(machine, handle_id, by_display)
        prev = machine.counted(q_id, handle)
        machine.retract(q_id, handle)
        self.sync_registry(board_id)
        withdrawn = (prev.ballot_id
                     if prev is not None and prev.channel == "ambient"
                     else None)
        return {
            "board_id": board_id,
            "q_id": q_id,
            "handle_id": handle,
            "display": state.handles[handle].display,
            "withdrawn_ballot_id": withdrawn,
            "had_effect": withdrawn is not None,
        }

    def invoke_tiebreak(self, board_id: str, ce_id: str, *,
                        by_display: str | None = None,
                        handle_id: str | None = None) -> TiebreakResult:
        """Open the tiebreak governance Q for one CE (story 20).

        Machine-enforced: facilitates mode only (plain :class:`VerdictError`
        otherwise), the CE must exist (:class:`UnknownCounterexample`), and
        one invocation per CE, ever (:class:`DuplicateTiebreak`). The room
        then votes ``for|against`` on ``tiebreak_q_id``; the machine settles
        it on a strict census majority or the 1-human exemption.
        """
        self.board(board_id)
        machine = self.machine(board_id)
        state = machine.state
        if ce_id not in state.ces:
            raise UnknownCounterexample(f"unknown ce: {ce_id}")
        handle = self._resolve_handle(machine, handle_id, by_display,
                                      required=False)
        q_id = machine.open_governance_q("tiebreak", subject=ce_id,
                                         opened_by=handle)
        return TiebreakResult(
            board_id=board_id, ce_id=ce_id, tiebreak_q_id=q_id,
            opened_by=handle,
            opened_seq=machine.state.questions[q_id].opened_seq,
        )

    def cast_tiebreak_ballot(self, board_id: str, ce_id: str,
                             reason: str) -> VoteResult:
        """The one labeled, reasoned facilitator ballot on the CE's
        refutation question (story 20).

        Only after that CE's tiebreak Q settled ``for``
        (:class:`TiebreakNotPassed`); exactly one, ever
        (:class:`DuplicateTiebreak`); no ``side`` parameter — the machine
        fixes ``rebutted`` (a lost vote cannot be bypassed into a refutation;
        a tie lands on not-refuted). The ballot counts in the tally but takes
        no census seat in facilitates mode.
        """
        self.board(board_id)
        machine = self.machine(board_id)
        state = machine.state
        if ce_id not in state.ces:
            raise UnknownCounterexample(f"unknown ce: {ce_id}")
        ballot_id = machine.tiebreak_ballot(ce_id, reason)
        node_id = state.ces[ce_id].node_id
        result = self._vote_result(machine, ballot_id,
                                   state.ballots[ballot_id].q_id)
        self.sync_registry(board_id)
        return result

    def vote_events(self, board_id: str, since_seq: int = 0) -> list[dict]:
        """Journal-sourced vote feed for SDF-14 (story 21).

        Every ``ballot_cast`` / ``retraction`` / ``tiebreak_ballot_cast``
        event after ``since_seq``, ascending. Pure read off
        ``journal.jsonl`` — never copied into the claim-only ``meta.jsonl``
        and never a new journal type. Journal seq and ``meta.jsonl`` seq are
        independent: correlate by ``ballot_id``/``ce_id``, not seq.
        """
        self.board(board_id)
        return [{"seq": e["seq"], "type": e["type"], "payload": e["payload"]}
                for e in self.journals.read_all(board_id)
                if e["type"] in VOTE_EVENT_TYPES and e["seq"] > since_seq]

    def scoreboard(self, board_id: str, node_id: str | None = None) -> dict:
        """Live scoreboard for one claim node (AC4, SDF-10's payload).

        Default scope is the active claim; an explicit ``node_id`` wins
        (score any node, including frozen history). Claimless boards are
        :class:`NoActiveClaim`; unknown nodes :class:`UnknownNode`.
        JSON-able by construction: ``json.loads(json.dumps(sb)) == sb``.
        """
        self.board(board_id)
        machine = self.machine(board_id)
        state = machine.state
        target = node_id if node_id is not None else state.active_node_id
        if target is None:
            raise NoActiveClaim(
                f"board {board_id} has no active claim to score")
        if target not in state.nodes:
            raise UnknownNode(f"unknown node: {target}")
        return scoreboard_view(machine, target)

    # -- scrutiny internals ---------------------------------------------------

    @staticmethod
    def _resolve_handle(machine: VerdictMachine, handle_id: str | None,
                        by_display: str | None, *,
                        required: bool = True) -> str | None:
        """Exactly one of ``handle_id``/``by_display`` (``handle_id`` wins).

        Known displays resolve to their existing handle so one claimant is
        never split into two identities; unknown displays enroll once. With
        ``required=False`` (alleger / tiebreak invoker) a blank or absent
        display is anonymous ``None``; with ``required=True`` (voters) it is
        a :class:`ValueError`.
        """
        state = machine.state
        if handle_id is not None:
            if handle_id not in state.handles:
                raise UnknownHandle(f"unknown handle: {handle_id}")
            return handle_id
        if by_display is None:
            if required:
                raise ValueError(
                    "a voter handle is required (handle_id or by_display)")
            return None
        if not isinstance(by_display, str) or not by_display.strip():
            if required:
                raise ValueError("by_display must be a non-blank string")
            return None
        for hid, handle in state.handles.items():
            if handle.display == by_display:
                return hid
        return machine.enroll_handle(str(by_display), kind="enrolled")

    def _ingest_vote(self, board_id: str, q_id: str, channel: str,
                     side: str, *, by_display: str | None = None,
                     handle_id: str | None = None, reason: str | None = None,
                     receive_time: float | None = None) -> VoteResult:
        """Shared body of ``cast_vote`` / ``record_ambient_vote": resolve,
        one machine call, shape the result, sync the registry mirrors."""
        self.board(board_id)
        machine = self.machine(board_id)
        state = machine.state
        if q_id not in state.questions:
            raise UnknownQuestion(f"unknown question: {q_id}")
        handle = self._resolve_handle(machine, handle_id, by_display)
        prev = machine.counted(q_id, handle)
        if channel == "explicit":
            ballot_id = machine.cast(q_id, handle, channel, side,
                                     reason=reason,
                                     receive_time=receive_time)
        else:
            ballot_id = machine.record_ambient(q_id, handle, side,
                                               receive_time=receive_time)
        replaced = (prev.ballot_id
                    if prev is not None and prev.ballot_id != ballot_id
                    else None)
        result = self._vote_result(machine, ballot_id, q_id, replaced=replaced)
        self.sync_registry(board_id)
        return result

    def _vote_result(self, machine: VerdictMachine, ballot_id: str,
                     q_id: str, replaced: str | None = None) -> VoteResult:
        """Shape a :class:`VoteResult` from the machine's post-state."""
        state = machine.state
        ballot = state.ballots[ballot_id]
        question = state.questions[q_id]
        subject = question.subject
        if question.kind in ("refutation", "tiebreak") \
                and subject in state.ces:
            ce_id: str | None = subject
            node_id: str = state.ces[subject].node_id
        else:
            ce_id = None
            node_id = state.active_node_id or ""
        counted = V.counted_ballot(state, q_id, ballot.handle_id)
        counted_now = counted is not None and counted.ballot_id == ballot_id
        # Fused from panel a: `replaced` names the ballot that lost its
        # place — only when the new ballot actually counts. A shadowed
        # ambient that loses to an explicit replaces nothing (None).
        if not counted_now:
            replaced = None
        seq = next((e["seq"] for e in reversed(machine.events)
                    if e["type"] in VOTE_EVENT_TYPES
                    and e["payload"].get("ballot_id") == ballot_id),
                   ballot.seq)
        return VoteResult(
            board_id=state.board_id,
            node_id=node_id,
            ce_id=ce_id,
            q_id=q_id,
            ballot_id=ballot_id,
            handle_id=ballot.handle_id,
            display=state.handles[ballot.handle_id].display,
            channel=ballot.channel,
            side=ballot.side,
            reason=ballot.reason,
            counted=bool(counted_now),
            replaced_ballot_id=replaced,
            seq=seq,
            refuted=(bool(machine.is_refuted(node_id))
                     if node_id and node_id in state.nodes else False),
        )

    # -- internals ---------------------------------------------------------------

    def _register_claim(self, board_id: str, text: str | None, *, kind: str,
                        sense_id: str | None = None,
                        claimant_display: str,
                        in_response_to: str | None = None,
                        revision: bool = False) -> ClaimResult:
        machine = self.machine(board_id)
        state = machine.state
        record = self.board(board_id)
        if state.status == "closed":
            raise BoardClosed(f"board {board_id} is closed")
        prev = state.active_node_id
        if revision and prev is None:
            raise NoActiveClaim(
                f"board {board_id} has no active claim to revise")
        if not revision and prev is not None:
            raise ClaimAlreadyActive(
                f"board {board_id} already has active claim {prev}; "
                f"use revise()")

        # All resolution happens before the first mutation so a bad sense_id,
        # a bad in_response_to or a blank text leaves every count untouched.
        sense: dict | None = None
        snapshot: dict | None = None
        if kind == "canonical":
            snapshot = self.canonical_store.cached(record.x_norm)
            if snapshot is None:
                raise NoCanonicals(
                    f"no canonical snapshot cached for {record.x!r} "
                    f"(pull was deferred); claim_original() still works")
            if snapshot.get("state") == "empty":
                raise EmptyCanonicals(
                    f"no canonical definitions for {record.x!r}")
            sense = self._resolve_sense(snapshot, sense_id)
            text = sense["gloss"]
        if not isinstance(text, str) or not text.strip():
            raise BlankClaim("claim text must be a non-blank string")

        if in_response_to is not None:
            if prev is None:
                raise ValueError(
                    "in_response_to requires an active claim to respond to")
            if in_response_to not in state.nodes[prev].ce_ids:
                raise ValueError(
                    f"in_response_to {in_response_to!r} is not a "
                    f"counterexample on {prev}")

        pending = self._pending_refutations(state, prev)
        node_id = self._next_node_id(state)
        claimed_by = self._ensure_handle(machine, claimant_display)

        machine.register_node(node_id, text)  # the ONLY canvas mutation

        # Nothing past this point may raise: a failure between the journal
        # append and the sidecar append would desync the two logs.
        node = machine.state.nodes[node_id]
        frozen_q_ids = [p["q_id"] for p in pending
                        if machine.state.questions[p["q_id"]].status
                        == "frozen"]
        unresolved = self._unresolved_ces(machine.state, prev, pending)
        provenance = (
            canonical_provenance(node_id=node_id, sense=sense or {},
                                 x=str(snapshot.get("x")) if snapshot
                                 else None,
                                 pulled_at=snapshot.get("pulled_at")
                                 if snapshot else None,
                                 claimed_by=claimed_by)
            if kind == "canonical"
            else original_provenance(node_id=node_id, claimed_by=claimed_by)
        )
        recorded_payload = {
            "node_id": node_id,
            "version": node.version,
            "text": node.text,
            "prev_node_id": prev,
            "is_revision": prev is not None,
            "claimed_by": claimed_by,
            "kind": provenance.kind,
            "provenance": provenance.to_dict(),
        }
        ts = self._clock()
        self.meta.append_event(board_id, CLAIM_RECORDED,
                               recorded_payload, ts=ts)
        revision_event: dict | None = None
        if prev is not None:
            revised_payload = {
                "tray": TRAY_NAME,
                "prev_node_id": prev,
                "new_node_id": node_id,
                "prev_text": machine.state.nodes[prev].text,
                "new_text": node.text,
                "prev_version": machine.state.nodes[prev].version,
                "new_version": node.version,
                "frozen_q_ids": list(frozen_q_ids),
                "unresolved_ces": unresolved,
                "prev_node_refuted": (
                    machine.state.nodes[prev].status == "refuted"),
                "in_response_to": in_response_to,
                "claimed_by": claimed_by,
            }
            self.meta.append_event(board_id, CLAIM_REVISED, revised_payload,
                                   ts=ts)
            revision_event = {"type": CLAIM_REVISED,
                              "payload": revised_payload}
        return ClaimResult(
            board_id=board_id, node_id=node_id, version=node.version,
            text=node.text, is_active=bool(node.is_active),
            prev_node_id=prev, is_revision=prev is not None,
            frozen_q_ids=frozen_q_ids, provenance=provenance.to_dict(),
            revision_event=revision_event,
        )

    @staticmethod
    def _resolve_sense(snapshot: dict, sense_id: str | None) -> dict:
        """Pick a sense out of the cached snapshot dicts (no chain call)."""
        senses = list(snapshot.get("senses", []))
        if not senses:
            raise EmptyCanonicals("canonical snapshot carries no senses")
        if sense_id is None:
            return senses[0]
        for sense in senses:
            if sense.get("sense_id") == sense_id:
                return sense
        known = [s.get("sense_id") for s in senses]
        raise UnknownSense(
            f"unknown sense {sense_id!r}; this X has {known}")

    @staticmethod
    def _pending_refutations(state: BoardState,
                             prev: str | None) -> list[dict]:
        """CEs on the superseded node whose questions are still open.

        Snapshot **before** ``register_node``: afterwards those questions are
        frozen, so this is the only moment the "carried unvoted" set exists.
        """
        if prev is None:
            return []
        pending = []
        for ce_id in state.nodes[prev].ce_ids:
            ce = state.ces[ce_id]
            q = state.questions[ce.q_id]
            if q.status == "open":
                pending.append({"ce_id": ce_id, "q_id": q.q_id,
                                "node_id": prev, "shape": ce.shape})
        return pending

    @staticmethod
    def _unresolved_ces(state: BoardState, prev: str | None,
                        pending: list[dict]) -> list[dict]:
        """Per-CE verdict snapshot after the freeze (SDF-7's tray input).

        ``carried`` comes from :func:`board.verdicts.is_standing` — never from
        ``outcome``: a 1–1 tie stands and is carried while ``outcome`` is
        ``None`` (issue 02: ties stand). ``carried: false`` entries are kept
        as the faithful record; SDF-7 filters.
        """
        rows: list[dict] = []
        if prev is None:
            return rows
        for entry in pending:
            q = state.questions[entry["q_id"]]
            stands, rebutted = V.standing_counts(state, entry["ce_id"])
            rows.append({
                "ce_id": entry["ce_id"],
                "q_id": entry["q_id"],
                "node_id": entry["node_id"],
                "shape": entry["shape"],
                "q_status": q.status,
                "outcome": V.refutation_outcome(state, entry["ce_id"]),
                "stands": int(stands),
                "rebutted": int(rebutted),
                "census_size": len(V.census(state, entry["q_id"])),
                "carried": bool(V.is_standing(state, entry["ce_id"])),
            })
        return rows

    @staticmethod
    def _next_node_id(state: BoardState) -> str:
        """Mint the next ``n{k}`` (caller-minted ids are the machine's rule)."""
        k = len(state.nodes) + 1
        while f"n{k}" in state.nodes:
            k += 1
        return f"n{k}"

    @staticmethod
    def _ensure_handle(machine: VerdictMachine, display: str) -> str | None:
        """Route a display name to a handle, enrolling it once.

        Exact-display lookup first: ``enroll_handle`` suffixes a duplicate
        (``Thrasymachus`` → ``Thrasymachus (2)``), which would silently split
        one claimant into two identities.
        """
        if display is None or (isinstance(display, str) and not display.strip()):
            return None
        state = machine.state
        for handle_id, handle in state.handles.items():
            if handle.display == display:
                return handle_id
        return machine.enroll_handle(str(display), kind="enrolled")


__all__ = ["BoardService"]
