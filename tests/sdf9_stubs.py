"""SDF-9 test helpers: the Justice arc on the stubbed SDF-5 service.

No pytest import here (mirrors ``tests/sdf5_stubs.py``). One helper builds a
board with the named handles enrolled; another settles a governance Q by
explicit votes; the third folds the persisted journal for replay assertions.
"""

from __future__ import annotations

from types import SimpleNamespace

from board.store import JsonlStore

HUMANS = ("Cephalus", "Polemarchus", "Thrasymachus")
CLAIM = "Justice is the advantage of the stronger."
REVISION = "Justice is the advantage of the stronger, refined."


def open_justice(svc, *, humans=HUMANS):
    """Fresh Justice board with the named handles enrolled."""
    opened = svc.open_board("Justice")
    board_id = opened.board_id
    machine = svc.machine(board_id)
    h = {display: machine.enroll_handle(display) for display in humans}
    return SimpleNamespace(service=svc, board_id=board_id, machine=machine,
                           h=h)


def settle_side(machine, q_id, voters, side):
    """Cast ``side`` from each voter until the Q leaves ``open``."""
    for handle_id in voters:
        if machine.q_status(q_id)[0] != "open":
            break
        machine.cast(q_id, handle_id, "explicit", side)
    return machine.q_status(q_id)


def reload_state(svc, board_id):
    """Fold the persisted journal through the same reducer (AC4 pattern)."""
    return JsonlStore(home=svc.root).load_state(board_id)


__all__ = [
    "HUMANS", "CLAIM", "REVISION",
    "open_justice", "settle_side", "reload_state",
]
