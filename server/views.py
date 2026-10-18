"""SDF-5 minimal views: JSON-able projections of board state (no UI).

Pure functions only — no IO, no mutation, no verdict recompute. Every
verdict number surfaced here is *read* from :mod:`board.verdicts` (the
single authority) over the live ``BoardState``, so a view can never drift
from what the machine counted. ``node.status`` is likewise the *stored*
status: ``VerdictMachine`` keeps the active node's status fresh on every
tally change, so re-deriving it here would be a second opinion, not a fact.

SDF-10 renders these; ``json.loads(json.dumps(view)) == view`` holds for
every shape (tuples become lists).
"""

from __future__ import annotations

from typing import Any

import board.verdicts as V
from board.roles import seats_view
from board.model import BoardState
from search.model import (
    COUNTEREXAMPLES_SECTION_KIND,
    ON_DEMAND_SECTION_LABEL,
)
from search.service import render_on_demand
from server.model import SEARCH_RECORDED, SEP_ADMITTED

NOT_PULLED = "not_pulled"


def _handle_sort_key(handle_id: str) -> tuple:
    """h1 < h2 < h10 — ids are machine-minted ``n<seq>``."""
    text = str(handle_id)
    for index, ch in enumerate(text):
        if ch.isdigit():
            return (int(text[index:]), text)
    return (0, text)


def node_view(node,
              provenance: dict | None = None) -> dict[str, Any]:
    """One version node: text, lineage, its CEs and its claim provenance."""
    return {
        "node_id": node.node_id,
        "version": node.version,
        "text": node.text,
        "status": node.status,
        "is_active": bool(node.is_active),
        "ce_ids": list(node.ce_ids),
        "provenance": dict(provenance) if provenance else None,
    }


def question_view(state: BoardState, q) -> dict[str, Any]:
    """One question: status/outcome plus the counted tally and census."""
    tally = dict(V.tally(state, q.q_id))
    return {
        "q_id": q.q_id,
        "kind": q.kind,
        "status": q.status,
        "subject": q.subject,
        "outcome": q.outcome,
        "opened_by": q.opened_by,
        "opened_seq": q.opened_seq,
        "census_size": len(V.census(state, q.q_id)),
        "tally": tally,
    }


def canonicals_view(snapshot: dict | None) -> dict[str, Any]:
    """The per-X canonical panel; ``None`` means the pull is still deferred."""
    if snapshot is None:
        return {
            "x": None,
            "state": NOT_PULLED,
            "empty_reason": None,
            "pulled_at": None,
            "senses": [],
        }
    senses = []
    for sense in snapshot.get("senses", []):
        cites = [dict(c) for c in sense.get("cites", [])]
        agrees = list(dict.fromkeys(
            str(cite.get("source", "")) for cite in cites if str(cite.get("source", ""))))
        senses.append({
            "sense_id": sense.get("sense_id"),
            "gloss": sense.get("gloss"),
            "pos": sense.get("pos"),
            "agrees": agrees,
            "n_cites": len(cites),
            "wiktionary_sense_no": sense.get("wiktionary_sense_no"),
            "cites": cites,
        })
    return {
        "x": snapshot.get("x"),
        "state": snapshot.get("state"),
        "empty_reason": snapshot.get("empty_reason"),
        "pulled_at": snapshot.get("pulled_at"),
        "senses": senses,
    }


def on_demand_view(events: list[dict]) -> dict[str, Any]:
    """The on-demand counterexample section (SDF-16): web + SEP voices.

    Structurally separate from :func:`canonicals_view` — these are one
    voice among many, never canonical definitions — folded from
    already-persisted ``search_recorded`` / ``sep_admitted`` meta events
    (file order == seq order). Pure read of envelopes; JSON-able."""
    searches = [e for e in events if e.get("type") == SEARCH_RECORDED]
    seps = [e for e in events if e.get("type") == SEP_ADMITTED]
    section: dict[str, Any] = {
        "kind": COUNTEREXAMPLES_SECTION_KIND,
        "label": ON_DEMAND_SECTION_LABEL,
    }
    section.update(render_on_demand(searches, seps))
    return section


def board_view(record, state: BoardState, provenance_map: dict[str, dict],
               snapshot: dict | None, *,
               shared_cache: bool = False,
               on_demand_events: list[dict] | None = None) -> dict[str, Any]:
    """Whole-board view: header, handles, lineage (v1→vN), questions, defs.

    ``mode``/``medium``/``status`` are read from the live machine state, not
    from the registry mirror, so a mid-dialogue toggle is visible immediately.
    """
    nodes = sorted(state.nodes.values(),
                   key=lambda n: (n.version, _handle_sort_key(n.node_id)))
    questions = sorted(state.questions.values(), key=lambda q: q.opened_seq)
    on_demand = on_demand_view(on_demand_events or [])
    return {
        "board_id": record.board_id,
        "x": record.x,
        "x_title": state.x_title,
        "label": record.label,
        "mode": state.mode,
        "medium": state.medium,
        "status": state.status,
        "seq": state.seq,
        "handles": [
            h.to_dict() for _, h in
            sorted(state.handles.items(),
                   key=lambda item: _handle_sort_key(item[0]))
        ],
        "active_node_id": state.active_node_id,
        "nodes": [node_view(n, provenance_map.get(n.node_id))
                  for n in nodes],
        "questions": [question_view(state, q) for q in questions],
        "roles": dict(seats_view(state)),
        "canonicals": canonicals_view(snapshot),
        # SDF-16: one on-demand section under two alias keys — never inside
        # "canonicals"; searches[] are web voices, sep[] are philosopher
        # voices, both canonical False.
        "on_demand": on_demand,
        "counterexamples": on_demand,
        "cache": {"shared": bool(shared_cache), "source": "registry"},
    }


def boards_view(records: list) -> list[dict[str, Any]]:
    """Compact board list for a picker/second-board UI."""
    return [{
        "board_id": r.board_id,
        "x": r.x,
        "x_title": r.x_title,
        "label": r.label,
        "mode": r.mode,
        "medium": r.medium,
        "status": r.status,
        "created_at": r.created_at,
    } for r in records]


# -- SDF-6 live scoreboard (pure reads over the machine's verdicts) ---------


def vote_rows(machine, q_id: str) -> list[dict[str, Any]]:
    """Who voted what on one question (AC4): every Ballot on ``q_id``,
    oldest-first by ``(receive_time, seq)`` — the exact order the machine
    uses to pick each handle's counted ballot.

    ``is_counted`` is the machine's counted-ballot decision for that handle
    (latest explicit beats any ambient; withdrawals invisible). Withdrawn
    ballots render ``withdrawn=True, is_counted=False``; the ballot they
    displaced (e.g. an older ambient) may still count.
    """
    state = machine.state
    # Fused from panel a: unknown questions render empty instead of
    # raising KeyError (V.counted raises on unknown q) — views never crash.
    counted_by_handle: dict[str, str] = {}
    for handle_id, ballot in (V.counted(state, q_id)
                               if q_id in state.questions else {}).items():
        counted_by_handle[handle_id] = ballot.ballot_id
    rows: list[dict[str, Any]] = []
    for b in sorted(
            (b for b in state.ballots.values() if b.q_id == q_id),
            key=lambda b: (b.receive_time, b.seq)):
        rows.append({
            "ballot_id": b.ballot_id,
            "handle_id": b.handle_id,
            # Fused from panel a: missing handles render None, never KeyError.
            "display": (state.handles[b.handle_id].display
                        if b.handle_id in state.handles else None),
            "channel": b.channel,
            "side": b.side,
            "reason": b.reason,
            "labeled": bool(b.labeled),
            "receive_time": b.receive_time,
            "seq": b.seq,
            "is_counted": counted_by_handle.get(b.handle_id) == b.ballot_id,
            "withdrawn": bool(b.withdrawn),
        })
    return rows


def _tiebreak_view(machine, ce) -> dict[str, Any]:
    """Tiebreak-invoke governance block for one CE row (story 20).

    ``invoked`` mirrors ``ce.tiebreak_invoked`` (set once, at invocation);
    ``voter``/``side``/``reason`` describe the one labeled facilitator ballot
    and stay ``None`` until it is cast.
    """
    state = machine.state
    none_block: dict[str, Any] = {
        "invoked": False, "q_id": None, "status": None, "outcome": None,
        "ballot_id": None, "voter": None, "display": None, "side": None,
        "reason": None, "votes": [],
    }
    if not ce.tiebreak_invoked:
        return none_block
    tb_q = next(
        (q for q in state.questions.values()
         if q.kind == "tiebreak" and q.subject == ce.ce_id), None)
    if tb_q is None:
        return none_block
    ballot = state.ballots.get(ce.tiebreak_ballot_id) \
        if ce.tiebreak_ballot_id is not None else None
    voter = ballot.handle_id if ballot is not None else None
    return {
        "invoked": True,
        "q_id": tb_q.q_id,
        "status": tb_q.status,
        "outcome": tb_q.outcome,
        "ballot_id": ce.tiebreak_ballot_id,
        "voter": voter,
        "display": (state.handles[voter].display
                    if voter is not None else None),
        "side": ballot.side if ballot is not None else None,
        "reason": ballot.reason if ballot is not None else None,
        "votes": vote_rows(machine, tb_q.q_id),
    }


def ce_rows(machine, node_id: str) -> list[dict[str, Any]]:
    """Live scoreboard rows for every CE attached to ``node_id`` (AC4).

    One row per CE in attachment order; every number is read from
    :mod:`board.verdicts` over the live state, never recomputed here."""
    state = machine.state
    node = state.nodes[node_id]
    rows: list[dict[str, Any]] = []
    for ce_id in node.ce_ids:
        ce = state.ces[ce_id]
        q = state.questions[ce.q_id]
        tally = dict(V.tally(state, ce.q_id))
        opened_by = q.opened_by
        rows.append({
            "ce_id": ce.ce_id,
            "shape": ce.shape,
            "q_id": ce.q_id,
            "q_status": q.status,
            "opened_by": opened_by,
            "display": (state.handles[opened_by].display
                        if opened_by is not None else None),
            "tally": tally,
            "census_size": len(V.census(state, ce.q_id)),
            "is_standing": bool(V.is_standing(state, ce.ce_id)),
            "is_refuted": bool(V.ce_is_refuted(state, ce.ce_id)),
            "outcome": V.refutation_outcome(state, ce.ce_id),
            "tie_exemption": V.tie_exemption_handle(state, ce.q_id),
            "decisive_side": V.decisive_side(state, ce.q_id),
            "votes": vote_rows(machine, ce.q_id),
            "tiebreak": _tiebreak_view(machine, ce),
        })
    return rows


def scoreboard_view(machine, node_id: str) -> dict[str, Any]:
    """Live scoreboard for one claim node: header verdict + CE rows (AC4).

    ``is_refuted`` is the machine's node-level predicate (some attached CE
    refutes under the strict census-majority rule); ``node_status`` is the
    stored status the machine keeps fresh on every tally change."""
    state = machine.state
    return {
        "board_id": state.board_id,
        "node_id": node_id,
        "claim_id": node_id,
        "node_status": state.nodes[node_id].status,
        "is_refuted": bool(V.is_refuted(state, node_id)),
        "ces": ce_rows(machine, node_id),
    }


__all__ = [
    "NOT_PULLED", "node_view", "question_view", "canonicals_view",
    "board_view", "boards_view",
    "vote_rows", "ce_rows", "scoreboard_view",
    "on_demand_view",
]
