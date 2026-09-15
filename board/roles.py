"""SDF-9 pure role reads — no IO, no mutation, stdlib only.

Seats are *stored truth*, never computed fallbacks (NOTES R2): the Socrates
seat is ``BoardState.socrates_handle_id`` and the active claim's defender is
``Node.defender`` on the active node. ``seat_holder``/``defender`` are thin
aliases over those fields, so live reads and journal replay (including
pre-SDF-9 journals, which load ``defender=None``) agree by construction.

This module deliberately imports nothing from :mod:`board.machine` or
:mod:`server`: the eligibility check takes the error class from the caller so
the machine can own the vocabulary without a roles -> machine import cycle.
No mandate scanning, no silent resolution order — consumers with a mandate
reading need (SDF-10/11) read the settled ``Question`` themselves.
"""

from __future__ import annotations

from board.model import BoardState


def defender(state: BoardState) -> str | None:
    """The active node's defender handle_id, or ``None`` while no claim.

    Pure derivation: ``None`` only when there is no active node or the active
    node was registered without a claimant. Defense follows activation
    automatically because nothing else is stored.
    """
    node_id = state.active_node_id
    if node_id is None:
        return None
    node = state.nodes.get(node_id)
    return node.defender if node is not None else None


def seat_holder(state: BoardState) -> str | None:
    """The Socrates handle_id (stored truth; ``None`` only before first set)."""
    return state.socrates_handle_id


def seat_eligible(state: BoardState, handle_id: str) -> bool:
    """May ``handle_id`` hold a seat/defense?

    ``False`` iff the handle is the facilitator **and** the board is not in
    Participates mode. In Participates mode the facilitator-designated handle
    is a full participant (SDF-2 symmetry) and may hold every seat.
    """
    handle = state.handles.get(handle_id)
    if handle is None:
        return False
    return not (handle.is_facilitator and state.mode != "participates")


def check_seat_eligible(state: BoardState, handle_id: str,
                        error_cls: type[Exception]) -> None:
    """Raise ``error_cls`` when :func:`seat_eligible` is ``False``.

    The machine passes :class:`board.machine.FacilitatorHoldsNoSeat` so the
    vocabulary stays in the machine while the predicate stays pure.
    """
    if not seat_eligible(state, handle_id):
        raise error_cls(
            f"handle {handle_id!r} is the facilitator and cannot hold a "
            f"seat/defense outside participates mode")


def seats_view(state: BoardState) -> dict:
    """Fused from panel c's ``seats_view``/``roles_view`` intent, adapted
    to this tree's stored schema (``socrates_handle_id`` +
    per-node ``defender`` + one ``pending_defense_offer``).

    Pure read for the SDF-10 UI: who questions, who defends the active
    claim, the in-flight cede (if any), and every handle's seat list — so
    the display cannot disagree with what the machine enforces (defender
    == active claimant until an accepted cede moves it; Socrates seat is
    stored truth, never vacant after first assignment).
    """
    socrates = state.socrates_handle_id
    active = state.active_node_id
    active_node = state.nodes.get(active) if active is not None else None
    current_defender = active_node.defender if active_node is not None else None
    pending = (dict(state.pending_defense_offer)
               if state.pending_defense_offer is not None else None)
    seats_by_handle: dict[str, list[str]] = {}
    if socrates is not None:
        seats_by_handle.setdefault(socrates, []).append("socrates")
    if current_defender is not None:
        seats_by_handle.setdefault(current_defender, []).append("defense")
    return {
        "socrates": socrates,
        "defense": current_defender,
        "defense_node_id": active,
        "pending_cede": pending,
        "seats_by_handle": seats_by_handle,
    }


__all__ = ["defender", "seat_holder", "seat_eligible",
           "check_seat_eligible", "seats_view"]
