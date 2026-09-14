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
from board.model import BoardState

NOT_PULLED = "not_pulled"


def _handle_sort_key(handle_id: str) -> tuple:
    """h1 < h2 < h10 — ids are machine-minted ``n<seq>``."""
    text = str(handle_id)
    digits = ""
    for index, ch in enumerate(text):
        if ch.isdigit():
            return (int(text[index:]), text)
    return (0, text)


def node_view(state: BoardState, node,
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
    if q.kind == "refutation":
        tally = dict(V.tally(state, q.q_id))
    else:
        tally = dict(V.gov_tally(state, q.q_id))
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
        agrees: list[str] = []
        for cite in cites:
            source = str(cite.get("source", ""))
            if source and source not in agrees:
                agrees.append(source)
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


def board_view(record, state: BoardState, provenance_map: dict[str, dict],
               snapshot: dict | None, *,
               shared_cache: bool = False) -> dict[str, Any]:
    """Whole-board view: header, handles, lineage (v1→vN), questions, defs.

    ``mode``/``medium``/``status`` are read from the live machine state, not
    from the registry mirror, so a mid-dialogue toggle is visible immediately.
    """
    nodes = sorted(state.nodes.values(),
                   key=lambda n: (n.version, _handle_sort_key(n.node_id)))
    questions = sorted(state.questions.values(), key=lambda q: q.opened_seq)
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
        "nodes": [node_view(state, n, provenance_map.get(n.node_id))
                  for n in nodes],
        "questions": [question_view(state, q) for q in questions],
        "canonicals": canonicals_view(snapshot),
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


__all__ = [
    "NOT_PULLED", "node_view", "question_view", "canonicals_view",
    "board_view", "boards_view",
]
