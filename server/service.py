"""BoardService — SDF-5 board operations end to end + SDF-6 scrutiny.

The public API: open a board on ``(X, label)``, pull/serve
canonical definitions, claim one (source-tagged) or author an original,
revise the active claim into a new version node — then allege labeled
counterexamples, ingest explicit/ambient ballots, retract ambient ones,
and read the live scoreboard.

Division of authority (downstream SDF-7/10/14/18 depend on this):

* **Verdict state** is owned by ``board.machine.VerdictMachine`` and its
  per-board ``journal.jsonl``. This module is the *only* caller of
  ``register_node`` in the slice and never writes a verdict event itself;
  the SDF-6 scrutiny methods stay thin: resolve → one machine mutator →
  shape the result → ``sync_registry`` on the three verdict-affecting paths
  (``cast_vote``, ``record_ambient_vote``, ``retract_vote``)
  and never on reads or on ``allege`` (it cannot move a mirror).
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

import threading
from pathlib import Path
from typing import Callable

import board.verdicts as V
from board.machine import (
    BoardClosed,
    NotActiveNode,
    UnknownCounterexample,
    UnknownHandle,
    UnknownNode,
    UnknownQuestion,
    VerdictMachine,
)
from board.model import MEDIA, SHAPES, BoardState
from board.store import JsonlStore
from dictionary.chain import DictionaryChain, build_default_chain
from dictionary.normalize import normalize_x
from server.errors import (
    BlankClaim,
    ClaimAlreadyActive,
    EmptyCanonicals,
    GovernanceAlreadyOpen,
    NoActiveClaim,
    NoCanonicals,
    NotAGovernanceQuestion,
    UnknownBoard,
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
    TRAY_DISCARDED,
    TRAY_PRESSED,
    BoardRegistry,
    CanonicalStore,
    MetaLog,
    SystemLog,
    creation_key,
    registry_path,
)
from server.views import board_view, boards_view, scoreboard_view

# The two room moves this slice governs.
GOVERNANCE_MOVE_KINDS = ("close", "ingress_selection")


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
                                              chain=self._chain)
        self.meta = MetaLog(self.root)
        self.system = SystemLog(self.root)
        self._machines: dict[str, VerdictMachine] = {}
        self._machines_lock = threading.Lock()
        # Guards the board-machine cache only: creating a board's machine
        # replays its journal from disk, so two threads creating it at the
        # same moment must not each cache their own copy. A read holding a
        # stale copy would later overwrite the live machine and its newest
        # events. Mutations themselves stay serialized by the forum's POST
        # lock; reads never take that lock and stay parallel once the
        # machine is cached.

    # -- canonical chain (lazy: never built at import/construct) -----------

    def _chain(self) -> DictionaryChain:
        if self.chain is None:
            self.chain = build_default_chain()
        return self.chain

    # -- boards -------------------------------------------------------------

    def open_board(self, x: str, label: str | None = None, *,
                   medium: str = "async",
                   pull_canonicals: bool = True) -> OpenResult:
        """Get-or-create the board keyed by ``(normalize_x(X), label)``.

        Validation and the canonical pull happen *before* any write, so a bad
        argument or a dead dictionary leaves no half-open board.
        """
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
            if existing is not None:      # GET path: medium is ignored
                return OpenResult(
                    record=existing, created=False,
                    view=self.view(existing.board_id))

        if pull_canonicals:
            # first write wins per X; a second same-X board costs zero calls
            self.canonical_store.get(xn)

        record = self.registry.reserve(x=x, x_title=str(x).strip(),
                                       label=label, medium=medium)
        machine = VerdictMachine(self.journals, record.board_id)
        machine.create_board(record.board_id, str(x).strip(), medium)
        with self._machines_lock:
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
        with self._machines_lock:
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

        Call after medium/close effects (the SDF-6/8 contract). Never on
        a read path — :meth:`view` reads the machine directly.
        """
        state = self.machine(board_id).state
        return self.registry.mark(board_id,
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

    # -- carry tray (SDF-7) ----------------------------------------------------
    # The tray is a read projection, never verdict state: revisions already
    # fold standing CEs into the ``carried_unvoted`` sidecar rows and freeze
    # the superseded node's questions, so this section only surfaces those
    # rows, retires them on press/discard, and never touches the journal
    # except for the one new Q a press opens on the active node. Tray items
    # stay off verdicts and the canvas live path by construction: nothing
    # here writes a ballot, a tally, a node or an edge.

    def tray(self, board_id: str) -> dict:
        """Visible carry: unresolved CEs from superseded nodes."""
        self.board(board_id)
        state = self.machine(board_id).state
        return {
            "board_id": board_id,
            "tray": TRAY_NAME,
            "active_node_id": state.active_node_id,
            "items": self._tray_items(board_id),
        }

    def _tray_items(self, board_id: str) -> list[dict]:
        """Carried rows minus pressed/discarded ones, in carried order."""
        carried: dict[str, dict] = {}
        for event in self.meta.read_events(board_id, CLAIM_REVISED):
            for row in event["payload"].get("unresolved_ces", []):
                if row.get("carried"):
                    carried[row["ce_id"]] = {
                        **{k: row.get(k) for k in (
                            "ce_id", "q_id", "node_id", "shape",
                            "q_status", "outcome", "stands",
                            "rebutted", "census_size")},
                        "status": TRAY_NAME,
                    }
        resolved = set()
        for event in self.system.read_events(board_id):
            if event["type"] in (TRAY_PRESSED, TRAY_DISCARDED):
                resolved.add(event["payload"].get("ce_id"))
        return [item for ce_id, item in carried.items()
                if ce_id not in resolved]

    def _tray_item(self, board_id: str, ce_id: str) -> dict:
        """One live tray item, or refuse (unknown vs. resolved)."""
        state = self.machine(board_id).state
        if ce_id not in state.ces:
            raise UnknownCounterexample(f"unknown ce: {ce_id}")
        for item in self._tray_items(board_id):
            if item["ce_id"] == ce_id:
                return item
        raise ValueError(
            f"ce {ce_id!r} is not on the carry tray "
            f"(never carried, already pressed, or already discarded)")

    def press_tray_item(self, board_id: str, ce_id: str, *,
                        by_display: str | None = None,
                        handle_id: str | None = None) -> AllegationResult:
        """Re-open an unvoted tray item as a new Q on the active node.

        Same shape, fresh CE + fresh refutation Q via the machine (so the
        new ballot is ordinary verdict state); the old item retires through
        a ``tray_pressed`` system entry. Validation precedes every write:
        a refusal leaves journal and log untouched.
        """
        machine = self.machine(board_id)
        state = machine.state
        if state.status == "closed":
            raise BoardClosed(f"board {board_id} is closed")
        item = self._tray_item(board_id, ce_id)
        target = state.active_node_id
        if target is None:
            raise NoActiveClaim(
                f"board {board_id} has no active claim to press onto")
        handle = self._resolve_handle(machine, handle_id, by_display,
                                      required=False)
        new_ce, new_q = machine.open_refutation_q(
            target, item["shape"], opened_by=handle)
        self.system.append_event(
            board_id, TRAY_PRESSED,
            {"ce_id": ce_id, "from_node_id": item["node_id"],
             "new_ce_id": new_ce, "new_q_id": new_q,
             "node_id": target, "shape": item["shape"],
             "origin": "system"},
            ts=self._clock())
        return AllegationResult(
            board_id=board_id, node_id=target, ce_id=new_ce, q_id=new_q,
            shape=item["shape"], opened_by=handle,
            opened_seq=machine.state.questions[new_q].opened_seq,
        )

    def discard_tray_item(self, board_id: str, ce_id: str) -> dict:
        """Drop an unvoted tray item: a system-log entry, nothing else.

        Log-only by design (SDF-16 precedent), so it also lands on a closed
        board; the journal, the meta sidecar and every verdict stand as
        they were.
        """
        self.board(board_id)
        item = self._tray_item(board_id, ce_id)
        self.system.append_event(
            board_id, TRAY_DISCARDED,
            {"ce_id": ce_id, "node_id": item["node_id"],
             "shape": item["shape"], "origin": "system"},
            ts=self._clock())
        return {"board_id": board_id, "ce_id": ce_id,
                "node_id": item["node_id"], "discarded": True}

    # -- on-demand search + SEP admission (SDF-16) ---------------------------
    # Explicit triggers only. Nothing in open_board, claim, revise, vote,
    # tally, view or log paths calls these methods or anything they call.
    # All three validate before the first write, touch the machine never,
    # and write only to the meta sidecar — so they also work on closed
    # boards (the journal stays terminal).

    def search_counterexamples(self, board_id: str, *, triggered_by: str | None = None,
                               query: str | None = None,
                               count: int = 5) -> dict:
        """Deliberate web counterexample search for this board's X."""
        record = self.board(board_id)              # UnknownBoard, zero writes
        if self.search_provider is None:
            raise NoSearchProvider(
                f"no search provider configured for board {board_id}")
        if triggered_by is None:
            raise ValueError("triggered_by is required")
        _display_string(triggered_by, "triggered_by")   # validate, verbatim
        result = run_counterexample_search(
            record.x, provider=self.search_provider, query=query,
            limit=count)
        prior = self.meta.read_events(board_id, SEARCH_RECORDED)
        payload = {
            **result.to_dict(),
            "triggered_by": triggered_by,
            "search_id": f"srch{len(prior) + 1}",
        }
        self.meta.append_event(board_id, SEARCH_RECORDED, payload,
                               ts=self._clock())
        return payload

    def attach_sep(self, board_id: str, *, triggered_by: str | None = None,
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
        if triggered_by is None:
            raise ValueError("triggered_by is required")
        _display_string(triggered_by, "triggered_by")   # validate, verbatim
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
            "triggered_by": triggered_by,
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
            on_demand_events=self.meta.read_events(board_id),
            tray_items=self._tray_items(board_id))

    def boards_list(self, x: str | None = None) -> list[dict]:
        return boards_view(self.list_boards(x))

    # -- share + resume (SDF-18: stories 41, 42) ---------------------------
    # Share URLs are computed, never stored: identity stays (X, label) in
    # the registry, so rotating the URL can never rename a board. Resume
    # replays the journal from disk (kill/crash-safe), heals the system
    # log, drops ephemeral live mics, keeps durable centroids, and hands
    # guests the current URL to rejoin on.

    def share_quick_tunnel(self, board_id: str, port: int) -> dict:
        """One-command share: the Quick Tunnel command plus its report.

        Read-only: verifies the board exists, then returns ``{board_id,
        command, kind, stable, note}`` without touching registry, journal,
        or sidecars. The tunnel prints the real rotating
        ``*.trycloudflare.com`` URL at run time; re-print/re-QR each
        session — so there is no stored URL to go stale."""
        from server.share import quick_tunnel_command, share_info
        self.board(board_id)
        command = quick_tunnel_command(port)
        # The live URL is printed by the tunnel at run time (it rotates),
        # so the report describes the kind — never a stored URL.
        info = share_info("https://tunnel.trycloudflare.com")
        return {
            "board_id": board_id,
            "command": command,
            "kind": info["kind"],
            "stable": info["stable"],
            "note": info["note"],
        }

    def share_lan(self, board_id: str, host: str, port: int) -> dict:
        """QR LAN fallback: a joinable local URL with zero third parties.

        Read-only like :meth:`share_quick_tunnel`. ``qr_payload`` is what
        the QR encodes (the URL verbatim); v1 ships no QR dependency, so
        any QR printer turns it into a joinable code."""
        from server.share import lan_url, qr_payload, share_info
        self.board(board_id)
        url = lan_url(host, port)
        info = share_info(url)
        info["qr_payload"] = qr_payload(url)
        return {"board_id": board_id, **info}

    def resume_board(self, board_id: str, *, current_url: str,
                     live_mics=None, enrollment_store=None) -> dict:
        """Sleep/crash resume: decided state reloaded, mics dropped.

        Forces a from-disk replay (drops the cached machine so the journal
        is re-folded exactly as a fresh process would), heals the system
        log, drops this board's ephemeral live mics, counts (never
        touches) durable enrollment centroids, and reports the current URL
        for guests to rejoin on. Returns ``{board_id, x, label, seq,
        rejoin_url, dropped_live_mics, kept_centroids}``."""
        from server.share import rejoin_url as _rejoin
        record = self.board(board_id)
        if (not isinstance(current_url, str) or not current_url.strip()):
            raise ValueError(
                "resume needs the current non-blank share URL")
        with self._machines_lock:
            self._machines.pop(board_id, None)  # force journal replay from disk
        state = self.machine(board_id).state
        self._heal_log(board_id)
        dropped = (live_mics.drop_board(board_id)
                   if live_mics is not None else 0)
        kept = (list(enrollment_store.handles(board_id))
                if enrollment_store is not None else [])
        return {
            "board_id": board_id,
            "x": record.x,
            "label": record.label,
            "seq": state.seq,
            "rejoin_url": _rejoin(current_url),
            "dropped_live_mics": dropped,
            "kept_centroids": kept,
        }

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

    def vote_events(self, board_id: str, since_seq: int = 0) -> list[dict]:
        """Journal-sourced vote feed for SDF-14 (story 21).

        Every ``ballot_cast`` / ``retraction``
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
        ``required=False`` (alleger) a blank or absent
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
        if question.kind == "refutation" \
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
        """System log for a board, oldest first.

        Heals from the journal before reading, so a settlement that bypassed
        the service (the ``machine()`` escape hatch) is backfilled. Entries
        carry ids and counts, never chat voice; they must never be rendered
        as a person's post.
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
            "tally": dict(V.tally(state, q_id)),
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
        machine = self.machine(board_id)
        state = machine.state
        if state.status == "closed":            # terminality outranks validation
            raise BoardClosed(f"board {board_id} is closed")
        if kind not in GOVERNANCE_MOVE_KINDS:
            raise ValueError(
                f"kind must be one of {GOVERNANCE_MOVE_KINDS}, not {kind!r}")
        if opened_by is not None and opened_by not in state.handles:
            raise UnknownHandle(f"unknown handle: {opened_by}")
        existing = self._open_move_q_id(state, kind, subject)
        if existing is not None:
            raise GovernanceAlreadyOpen(
                f"{kind} is already open as {existing}")
        if kind == "ingress_selection":
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
            "tally": dict(V.tally(state, q.q_id)),
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

        Logs any settled non-refutation Q. Refusals and
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
        if q.kind == "close" and q.outcome == "for":
            self.sync_registry(board_id)

    def _heal_log(self, board_id: str) -> None:
        """Backfill system entries for governance Qs recorded in the journal.

        Covers every non-refutation Q (room moves) with the same payload builders the write
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
            # A hatch-opened move still needs its open entry: any
            # non-refutation Q missing its open entry is backfilled.
            if q.q_id not in have_opened:
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
        claimed_by = self._resolve_handle(machine, None, claimant_display,
                                          required=False)
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



__all__ = ["BoardService"]


def _display_string(value, name: str) -> str:
    """Non-blank display string (verbatim; never enrolled as a handle)."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-blank display string")
    return value
