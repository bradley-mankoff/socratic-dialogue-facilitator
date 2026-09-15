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
* **On-demand search + SEP** (SDF-16) are *explicit-trigger only*: a web
  provider is a constructor argument (never built here — no default provider,
  no key handling in this file), a trigger costs exactly one backend call,
  SEP admissions perform zero I/O, and both land in the meta sidecar —
  never in the journal, never in the canonical cache, never as nodes.

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
    FacilitatorHoldsNoSeat,
    FacilitatorNeverProposes,
    GovernanceAlreadyOpen,
    GovernanceNoOp,
    NoActiveClaim,
    NoCanonicals,
    NotAGovernanceQuestion,
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
    SEARCH_RECORDED,
    SEP_ADMITTED,
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
from search.backend import SearchBackend
from search.errors import BadSepSource, NoSearchProvider
from search.sep import make_sep_link, make_sep_paste, sep_entry_url
from search.service import (
    render_on_demand,
    search_counterexamples as run_counterexample_search,
)
from server.store import (
    DEFAULT_ROOT,
    GOVERNANCE_OPENED,
    GOVERNANCE_SETTLED,
    BoardRegistry,
    CanonicalStore,
    MetaLog,
    SystemLog,
    creation_key,
    registry_path,
)
from server.views import board_view, boards_view, scoreboard_view

# The five room moves this slice governs. ``tiebreak`` is excluded: it is the
# SDF-2 CE-dispute protocol invocation, not a room move (SDF-8 logs it only
# as a journal fact, never as a governance mandate).
GOVERNANCE_MOVE_KINDS = ("close", "mode_switch", "socrates_swap",
                         "active_claim_switch", "ingress_selection")


class BoardService:
    """One object per data root; every board under that root is reachable."""

    def __init__(self, root: Path | str = DEFAULT_ROOT, *,
                 chain: DictionaryChain | None = None,
                 clock: Callable[[], str] | None = None,
                 search_provider: SearchBackend | None = None) -> None:
        self.root = Path(root)
        self.chain = chain
        self._clock = clock or now_iso
        # SDF-16: stored verbatim, never constructed here. ``None`` (the
        # default) means no web capability exists on this service — the
        # trigger then refuses with NoSearchProvider before any I/O. There
        # is deliberately no env/config fallback: nothing automatic can
        # arm the web path.
        self.search_provider = search_provider
        self.journals = JsonlStore(self.root)
        self.registry = BoardRegistry(registry_path(self.root))
        self.canonical_store = CanonicalStore(self.root,
                                              chain=self._chain_or_get)
        self.meta = MetaLog(self.root)
        self.system = SystemLog(self.root)
        # Alias for cross-panel compatibility: panels b/c use
        # ``system_log`` while panels a/c use ``system``. Both names
        # reference the same fourth durable home (system.jsonl).
        self.system_log = self.system
        self._machines: dict[str, VerdictMachine] = {}

    @classmethod
    def open(cls, home: Path | str = Path("store"),
             chain: DictionaryChain | None = None,
             clock: Callable[[], str] | None = None,
             search_provider: SearchBackend | None = None) -> "BoardService":
        """Re-open the data home; every board and snapshot comes from disk."""
        return cls(home, chain=chain, clock=clock,
                   search_provider=search_provider)

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

    # -- roles / seats (SDF-9) ------------------------------------------------

    def offer_defense(self, board_id: str, to_handle: str, *,
                      by: str) -> dict:
        """The active defender names a successor; nothing moves until
        accept (AC2). Handle refs resolve by exact id or display, never
        auto-enroll; the machine re-validates everything.

        Fused a+b: panel a's machine-direct call plus panel b's caller
        ergonomics — returns ``{"board_id", "from", "to", "node_id"}``
        (the committed payload) and syncs the registry mirror. The
        idempotent re-offer returns the original event's payload shape, so
        callers can read ``offered["to"]`` either way."""
        self.board(board_id)                      # UnknownBoard
        machine = self.machine(board_id)
        raw = machine.offer_defense(
            self._resolve_existing_handle(machine, to_handle),
            self._resolve_existing_handle(machine, by))
        payload = raw["payload"] if "payload" in raw else raw
        self.sync_registry(board_id)
        return {"board_id": board_id, **payload}

    def accept_defense(self, board_id: str, *, by: str) -> dict:
        """The offered target accepts; the active claim's defense moves.

        Fused a+b: same payload-plus-board_id shape as
        :meth:`offer_defense`."""
        self.board(board_id)
        machine = self.machine(board_id)
        raw = machine.accept_defense(
            self._resolve_existing_handle(machine, by))
        payload = raw["payload"] if "payload" in raw else raw
        self.sync_registry(board_id)
        return {"board_id": board_id, **payload}

    def decline_defense(self, board_id: str, *, by: str) -> dict:
        """The offered target declines; pending clears, defense stays.

        Fused from panel c's lifecycle: logs ``defense_cede_declined``.
        Only the offered ``to`` handle may decline."""
        self.board(board_id)
        machine = self.machine(board_id)
        raw = machine.decline_defense(
            self._resolve_existing_handle(machine, by))
        payload = raw["payload"] if "payload" in raw else raw
        self.sync_registry(board_id)
        return {"board_id": board_id, **payload}

    def withdraw_defense(self, board_id: str, *, by: str) -> dict:
        """The offerer withdraws; pending clears, defense stays.

        Fused from panel c's lifecycle: logs ``defense_cede_withdrawn``.
        Only the recorded ``from`` handle may withdraw."""
        self.board(board_id)
        machine = self.machine(board_id)
        raw = machine.withdraw_defense(
            self._resolve_existing_handle(machine, by))
        payload = raw["payload"] if "payload" in raw else raw
        self.sync_registry(board_id)
        return {"board_id": board_id, **payload}

    def roles(self, board_id: str) -> dict:
        """Fused from panel c: pure seat snapshot for headers/pickers."""
        self.board(board_id)
        machine = self.machine(board_id)
        from server.views import roles_view as _roles_view
        return _roles_view(machine.state)

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

    # -- on-demand search + SEP admission (SDF-16) ---------------------------
    # Explicit triggers only. Nothing in open_board, claim, revise, vote,
    # tally, view or log paths calls these methods or anything they call.
    # All three validate before the first write, touch the machine never,
    # and write only to the meta sidecar — so they also work on closed
    # boards (the journal stays terminal).

    def search_counterexamples(self, board_id: str, *, triggered_by: str | None = None,
                               requested_by: str | None = None,
                               query: str | None = None,
                               count: int = 5) -> dict:
        """Deliberate web counterexample search for this board's X.

        Costs exactly one backend call per trigger (never cached into
        canonicals, never pre-fired); the labeled result is appended to
        the meta sidecar as ``search_recorded`` and returned as a plain
        dict. ``triggered_by`` (alias ``requested_by``, fused from panel a)
        is stored verbatim as a display string — never enrolled as a
        handle (enrollment would write journal events, and this is not a
        room move). Both payload keys are always written so either
        spelling reads back identically.
        """
        record = self.board(board_id)              # UnknownBoard, zero writes
        if self.search_provider is None:
            raise NoSearchProvider(
                f"no search provider configured for board {board_id}")
        who = triggered_by if triggered_by is not None else requested_by
        if who is None:
            raise ValueError("triggered_by (or requested_by) is required")
        _display_string(who, "triggered_by")   # validate, verbatim
        result = run_counterexample_search(
            record.x, provider=self.search_provider, query=query,
            limit=count)
        prior = self.meta.read_events(board_id, SEARCH_RECORDED)
        payload = {
            **result.to_dict(),
            "requested_by": who,
            "triggered_by": who,
            "search_id": f"srch{len(prior) + 1}",
        }
        self.meta.append_event(board_id, SEARCH_RECORDED, payload,
                               ts=self._clock())
        return payload

    def attach_sep(self, board_id: str, *, triggered_by: str | None = None,
                   requested_by: str | None = None,
                   url: str | None = None, excerpt: str | None = None,
                   speaker: str | None = None,
                   citation: str = "") -> dict:
        """Admit one SEP voice: a link-out URL or a pasted excerpt.

        Exactly one of ``url`` / ``excerpt`` (both or neither refuse with
        :class:`BadSepSource` and zero writes). A bare slug (no ``://``,
        no whitespace) expands to the SEP entry URL; a full URL must be
        https on exactly the SEP entry host (the one address
        :mod:`search.sep` admits). The excerpt is stored
        verbatim, capped at 2000 chars. **Zero I/O**: no fetch, no crawl,
        no validation request — the philosopher source is never touched
        by the server. ``speaker`` / ``triggered_by`` stay display
        strings, never enrolled handles.
        """
        record = self.board(board_id)
        who = triggered_by if triggered_by is not None else requested_by
        if who is None:
            raise ValueError("triggered_by (or requested_by) is required")
        _display_string(who, "triggered_by")   # validate, verbatim
        given = [name for name, value in (("url", url), ("excerpt", excerpt))
                 if value is not None]
        if len(given) != 1:
            raise BadSepSource(
                "exactly one of url= (link-out) or excerpt= (paste) "
                "is required")
        retrieved_at = self._clock()
        if given[0] == "url":
            entry = make_sep_link(self._expand_sep_url(url), x=record.x,
                                  citation=citation,
                                  retrieved_at=retrieved_at)
        else:
            entry = make_sep_paste(excerpt, x=record.x, citation=citation,
                                   speaker=speaker, url=None,
                                   retrieved_at=retrieved_at)
        prior = self.meta.read_events(board_id, SEP_ADMITTED)
        payload = {
            **entry.to_dict(),
            "triggered_by": who,
            "requested_by": who,
            "sep_id": f"sep{len(prior) + 1}",
        }
        self.meta.append_event(board_id, SEP_ADMITTED, payload,
                               ts=self._clock())
        return payload

    @staticmethod
    def _expand_sep_url(url: str) -> str:
        """Full SEP URL → verbatim; bare slug → entry URL; else refuse.

        A scheme-less dotted/host-shaped string is assumed https (then
        the strict host check in ``search.sep`` still applies); whitespace
        or blank is a paste confused with a link, and refuses.
        """
        text = str(url).strip()
        if not text:
            raise BadSepSource("a SEP link needs a non-blank URL")
        if "://" in text:
            return text
        if any(ch.isspace() for ch in text):
            raise BadSepSource(
                "that looks like prose, not a URL — pass excerpt= instead")
        if "/" in text or "." in text:
            return f"https://{text}"
        return sep_entry_url(text)

    def on_demand(self, board_id: str) -> dict:
        """Read path: ``{"searches": [...], "sep": [...]}`` in seq order.

        Pure read over the meta sidecar — no provider call, no canonical
        cache touch, no journal read.
        """
        self.board(board_id)
        return render_on_demand(
            self.meta.read_events(board_id, SEARCH_RECORDED),
            self.meta.read_events(board_id, SEP_ADMITTED),
        )

    def counterexamples(self, board_id: str) -> dict:
        """Alias of :meth:`on_demand` for SDF-10 renderers."""
        return self.on_demand(board_id)

    # -- views -----------------------------------------------------------------

    def view(self, board_id: str) -> dict:
        """JSON-able whole-board view (SDF-10's payload).

        The ``on_demand``/``counterexamples`` section is folded from this
        board's meta events (SDF-16): one voice material, never canonicals.
        """
        record = self.board(board_id)
        machine = self.machine(board_id)
        snapshot = self.canonical_store.cached(record.x_norm)
        return board_view(
            record, machine.state, self.provenance_map(board_id), snapshot,
            shared_cache=len(self.registry.boards_for(record.x_norm)) > 1,
            on_demand_events=self.meta.read_events(board_id))

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
        self._after_settlement(board_id, q_id)
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
        self._after_settlement(board_id, state.ballots[ballot_id].q_id)
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

    @staticmethod
    def _resolve_existing_handle(machine: VerdictMachine, ref: str) -> str:
        """Exact handle-id or exact-display lookup; never auto-enroll.

        SDF-9 cede paths name existing players only (a typo must refuse, not
        silently mint an identity): :class:`UnknownHandle` on any miss.
        """
        state = machine.state
        if not isinstance(ref, str) or not ref.strip():
            raise ValueError("handle id or display required")
        if ref in state.handles:
            return ref
        for handle_id, handle in state.handles.items():
            if handle.display == ref:
                return handle_id
        raise UnknownHandle(f"unknown handle: {ref}")

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
        self._after_settlement(board_id, q_id)
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
    # -- governance moves + system log (SDF-8) -----------------------------

    def propose_mode_switch(self, board_id: str, to_mode: str | None = None,
                            opened_by: str | None = None, *,
                            new_mode: str | None = None,
                            **kw) -> str:
        """Open a mode_switch Q (majority decides; mode flips on 'for')."""
        # Panel-b alias: ``new_mode`` kw. Panel-c positional style also works
        # since ``to_mode`` is positional-or-keyword with a default.
        target = to_mode if to_mode is not None else kw.pop(
            "to_mode", None)
        if target is None:
            target = new_mode if new_mode is not None else kw.pop(
                "new_mode", None)
        if kw:
            raise TypeError(f"unexpected kwargs: {sorted(kw)}")
        return self._open_move(board_id, "mode_switch", target, opened_by)

    def propose_socrates_swap(self, board_id: str, to_handle: str | None = None,
                              opened_by: str | None = None, *,
                              handle_id: str | None = None,
                              **kw) -> str:
        """Open a socrates_swap Q; the settled mandate is SDF-9's to apply."""
        target = to_handle if to_handle is not None else kw.pop(
            "to_handle", None)
        if target is None:
            target = handle_id if handle_id is not None else kw.pop(
                "handle_id", None)
        if kw:
            raise TypeError(f"unexpected kwargs: {sorted(kw)}")
        return self._open_move(board_id, "socrates_swap", target,
                               opened_by)

    def propose_active_claim_switch(self, board_id: str, to_node: str | None = None,
                                    opened_by: str | None = None, *,
                                    node_id: str | None = None,
                                    **kw) -> str:
        """Open an active_claim_switch Q; this slice never re-activates."""
        target = to_node if to_node is not None else kw.pop(
            "to_node", None)
        if target is None:
            target = node_id if node_id is not None else kw.pop(
                "node_id", None)
        if kw:
            raise TypeError(f"unexpected kwargs: {sorted(kw)}")
        return self._open_move(board_id, "active_claim_switch", target,
                               opened_by)

    def propose_ingress_selection(self, board_id: str, candidate: str,
                                  opened_by: str | None = None) -> str:
        """Open an ingress_selection Q; the candidate is opaque here."""
        return self._open_move(board_id, "ingress_selection", candidate,
                               opened_by)

    def propose_close(self, board_id: str,
                      opened_by: str | None = None) -> str:
        """Open a close Q. A settled 'for' freezes and closes the board."""
        return self._open_move(board_id, "close", None, opened_by)


    def governance_vote(self, board_id: str, q_id: str, handle_id: str,
                        side: str, channel: str = "explicit",
                        reason: str | None = None) -> str:
        """``cast_vote`` that refuses refutation Qs (governance moves only)."""
        q = self._governance_q(board_id, q_id)
        if channel == "ambient":
            result = self.record_ambient_vote(
                board_id, q.q_id, side, handle_id=handle_id)
        elif channel == "explicit":
            result = self.cast_vote(board_id, q.q_id, side,
                                    handle_id=handle_id, reason=reason)
        else:
            raise ValueError(f"unknown channel: {channel}")
        self._after_settlement(board_id, q.q_id)
        return result.ballot_id


    def force_settle(self, board_id: str, q_id: str) -> str | None:
        """Force a resolve attempt; returns the winning side or None.

        Fused (panels b/c): on an already-settled Q return its outcome
        without re-firing the machine, so terminal boards stay terminal
        through this read-back path. Refutation Qs report the live verdict
        without settling; every fresh settlement is logged."""
        machine = self.machine(board_id)
        q = machine.state.questions.get(q_id)
        if q is None:
            raise UnknownQuestion(f"unknown question: {q_id}")
        if q.status == "settled":
            # Idempotent read-back: never re-fire effects on a closed board.
            self._after_settlement(board_id, q_id)
            return q.outcome
        reported = machine.settle(q_id)
        self._after_settlement(board_id, q_id)
        q = machine.state.questions[q_id]
        return q.outcome if q.status == "settled" else reported

    def read_system_log(self, board_id: str,
                        kind: str | None = None) -> list[dict]:
        """Facilitator-blind system log for a board, oldest first.

        Heals from the journal before reading, so a settlement that bypassed
        the service (the ``machine()`` escape hatch) is backfilled. Entries
        carry ids and counts, never chat voice; they must never be rendered
        as facilitator contributions.
        """
        self.board(board_id)
        self._heal_log(board_id)
        return self.system.read_events(board_id, kind)

    def mandate_for(self, board_id: str, kind: str) -> dict | None:
        """Newest settled-'for' mandate of ``kind``, or None.

        The settled system-log entry IS the mandate: this slice records the
        room's choice for downstream consumers (SDF-9/11/18) to apply.
        """
        self.board(board_id)
        self._heal_log(board_id)
        newest = None
        for event in self.system.read_events(board_id, GOVERNANCE_SETTLED):
            payload = event["payload"]
            if payload.get("kind") != kind or payload.get("outcome") != "for":
                continue
            if (newest is None
                    or (payload.get("settled_seq") or 0)
                    > (newest["payload"].get("settled_seq") or 0)):
                newest = event
        if newest is None:
            return None
        payload = newest["payload"]
        mandate = {"kind": kind, "target": payload.get("subject"),
                   "q_id": payload.get("q_id"),
                   "settled_seq": payload.get("settled_seq")}
        if kind == "ingress_selection":
            mandate["consumer"] = "ingress"
        return mandate

    def governance_status(self, board_id: str, q_id: str) -> dict:
        """Live status/outcome/tally for one governance Q (never re-counts)."""
        q = self._governance_q(board_id, q_id)
        state = self.machine(board_id).state
        return {
            "q_id": q.q_id,
            "kind": q.kind,
            "subject": q.subject,
            "status": q.status,
            "outcome": q.outcome,
            "tally": dict(V.gov_tally(state, q_id)),
            "census_size": len(V.census(state, q_id)),
        }

    # -- governance internals ----------------------------------------------

    def _governance_q(self, board_id: str, q_id: str):
        state = self.machine(board_id).state
        q = state.questions.get(q_id)
        if q is None:
            raise UnknownQuestion(f"unknown question: {q_id}")
        if q.kind == "refutation":
            raise NotAGovernanceQuestion(
                f"question {q_id} is a refutation Q, not a governance Q")
        return q

    def _open_move(self, board_id: str, kind: str, subject: str | None,
                   opened_by: str | None) -> str:
        """Validate + open one governance Q; log the opening.

        Machine validation stays authoritative for kind/subject/closed-board
        rules; this wrapper adds the room-level rules the machine leaves to
        callers (unicast slots, no-op moves, subject existence) and appends
        the ``governance_opened`` system entry only after the Q exists.
        """
        self.board(board_id)                     # UnknownBoard
        machine = self.machine(board_id)
        state = machine.state
        if state.status == "closed":            # terminality outranks validation
            raise BoardClosed(f"board {board_id} is closed")
        if kind not in GOVERNANCE_MOVE_KINDS and kind != "tiebreak":
            raise ValueError(
                f"kind must be one of {GOVERNANCE_MOVE_KINDS}, not {kind!r}")
        if opened_by is not None and opened_by not in state.handles:
            raise UnknownHandle(f"unknown handle: {opened_by}")
        # Fused (panel b): the facilitator never proposes a close — checked
        # before the duplicate slot so the refusal is identical from any
        # position and leaves journal + log untouched.
        if (kind == "close" and opened_by is not None
                and state.handles[opened_by].is_facilitator):
            raise FacilitatorNeverProposes(
                "the facilitator never proposes a close")
        existing = self._open_move_q_id(state, kind, subject)
        if existing is not None:
            raise GovernanceAlreadyOpen(
                f"{kind} is already open as {existing}")
        if kind == "mode_switch":
            if subject not in MODES:
                raise ValueError(f"mode must be one of {MODES}")
            if state.mode == subject:
                raise GovernanceNoOp(f"board is already in {subject!r} mode")
        elif kind == "socrates_swap":
            if subject not in state.handles:
                raise UnknownHandle(f"unknown handle: {subject}")
        elif kind == "active_claim_switch":
            if subject not in state.nodes:
                raise UnknownNode(f"unknown node: {subject}")
            # Fused (panels a+b/c): NoOp when the target is already active —
            # via the canonical active pointer OR the node flag, so both
            # panel wordings agree.
            node = state.nodes.get(subject or "")
            if subject == state.active_node_id or (
                    node is not None and getattr(node, "is_active", False)):
                raise GovernanceNoOp(
                    f"node {subject} is already the active claim")
        elif kind == "ingress_selection":
            if not isinstance(subject, str) or not subject.strip():
                raise ValueError(
                    "ingress candidate must be a non-blank string")
        q_id = machine.open_governance_q(kind, subject=subject,
                                         opened_by=opened_by)
        self._log_opened(board_id, state.questions[q_id])
        return q_id

    @staticmethod
    def _open_move_q_id(state: BoardState, kind: str,
                        subject: str | None) -> str | None:
        """Open Q holding this move's slot, if any: unicast by kind,
        ingress by ``(kind, candidate)``."""
        for q_id, q in state.questions.items():
            if q.status != "open" or q.kind != kind:
                continue
            if kind != "ingress_selection" or q.subject == subject:
                return q_id
        return None

    @staticmethod
    def _opened_payload(q) -> dict:
        return {
            "q_id": q.q_id,
            "kind": q.kind,
            "subject": q.subject,
            "opened_by": q.opened_by,
            "opened_seq": q.opened_seq,
            "origin": "system",
        }

    @staticmethod
    def _settled_payload(state: BoardState, q) -> dict:
        """Build a ``governance_settled`` payload from machine state only.

        Fused: ids + tallies only (no ``opened_by`` in the settled payload,
        so panel b's strict key test passes while panel a's subset test
        still passes); the close tray is deep-copied whenever the outcome
        is ``for`` (panels b/c), never recomputed."""
        payload = {
            "q_id": q.q_id,
            "kind": q.kind,
            "subject": q.subject,
            "outcome": q.outcome,
            "tally": dict(V.gov_tally(state, q.q_id)),
            "census_size": len(V.census(state, q.q_id)),
            "settled_seq": q.settled_seq,
            "opened_seq": q.opened_seq,
            "origin": "system",
        }
        if q.kind == "close" and q.outcome == "for":
            payload["carried_unresolved"] = [
                dict(row) for row in (state.carried_unresolved or [])]
            payload["closed_seq"] = (state.canvas or {}).get("closed_seq")
        return payload

    def _log_opened(self, board_id: str, q) -> None:
        for event in self.system.read_events(board_id, GOVERNANCE_OPENED):
            if event["payload"].get("q_id") == q.q_id:
                return
        self.system.append_event(board_id, GOVERNANCE_OPENED,
                                 self._opened_payload(q), ts=self._clock())

    def _after_settlement(self, board_id: str, q_id: str) -> None:
        """Post-mutation hook: log a fresh settlement, mirror the registry.

        Fused: logs any settled non-refutation Q (the five room moves AND a
        tiebreak settled through service voting, per the approved plan R5/R6
        — panel c), so a full rebuild never drops a tiebreak. Refusals and
        open Qs log nothing. Dedupe is read-based (a ``governance_settled``
        entry for this ``q_id`` already on disk), so reloads and double
        hooks can never log a settlement twice. Never called from a read.
        """
        machine = self.machine(board_id)
        state = machine.state
        q = state.questions.get(q_id)
        if q is None or q.status != "settled":
            return
        if q.kind == "refutation":
            return
        for event in self.system.read_events(board_id, GOVERNANCE_SETTLED):
            if event["payload"].get("q_id") == q_id:
                return
        self.system.append_event(board_id, GOVERNANCE_SETTLED,
                                 self._settled_payload(state, q),
                                 ts=self._clock())
        if q.kind in ("mode_switch", "close") and q.outcome == "for":
            self.sync_registry(board_id)

    def _heal_log(self, board_id: str) -> None:
        """Backfill system entries for governance Qs recorded in the journal.

        Fused (panels b/c): covers every non-refutation Q (room moves AND
        tiebreak, per plan R5/R6) with the same payload builders the write
        path uses, appended interleaved by journal seq
        (``opened_seq``/``settled_seq``) so a total-file-loss rebuild is
        line-identical to the normal path. Read-based dedupe keeps a second
        read from duplicating anything. Covers the ``machine()`` escape
        hatch: a direct machine vote can push the projection behind, but
        never corrupt it.
        """
        machine = self.machine(board_id)
        state = machine.state
        existing = self.system.read_events(board_id)
        have_opened = {e["payload"].get("q_id") for e in existing
                       if e.get("type") == GOVERNANCE_OPENED}
        have_settled = {e["payload"].get("q_id") for e in existing
                        if e.get("type") == GOVERNANCE_SETTLED}
        # Collect missing opens/settles, then sort by journal seq so the
        # healed order matches the order the normal path would have written.
        backlog: list[tuple[int, str, str]] = []
        for q in state.questions.values():
            if q.kind == "refutation":
                continue
            # Only room moves have ``governance_opened`` via _open_move, but
            # a hatch-opened move or tiebreak still needs its open entry.
            if q.q_id not in have_opened:
                # Room moves + tiebreak: any non-refutation Q missing its
                # open entry is backfilled (panel c chronological test).
                backlog.append((q.opened_seq or 0, "open", q.q_id))
            if (q.status == "settled" and q.q_id not in have_settled):
                backlog.append((q.settled_seq or q.opened_seq or 0,
                                "settle", q.q_id))
        if not backlog:
            return
        backlog.sort(key=lambda row: row[0])
        by_id = {q.q_id: q for q in state.questions.values()}
        for _, what, q_id in backlog:
            q = by_id[q_id]
            if what == "open":
                # Skip tiebreak opens that predate the move kinds? No — the
                # plan requires tiebreak heals consistently, so log it.
                self.system.append_event(board_id, GOVERNANCE_OPENED,
                                         self._opened_payload(q),
                                         ts=self._clock())
                have_opened.add(q_id)
            else:
                self.system.append_event(board_id, GOVERNANCE_SETTLED,
                                         self._settled_payload(state, q),
                                         ts=self._clock())
                have_settled.add(q_id)

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
        if (claimed_by is not None
                and machine.state.handles[claimed_by].is_facilitator
                and machine.state.mode != "participates"):
            raise FacilitatorHoldsNoSeat(
                "the facilitator cannot hold the defense outside "
                "participates mode")             # G2

        machine.register_node(node_id, text, defender=claimed_by)  # canvas

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


def _display_string(value, name: str) -> str:
    """Non-blank display string (verbatim; never enrolled as a handle)."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-blank display string")
    return value
