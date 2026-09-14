"""SDF-6 shared fixtures: a Justice board with a claim, reached only
through the :class:`server.service.BoardService` scrutiny API.

Zero live HTTP (the chain is stubbed; canonical pulls are deferred) and a
fixed clock, mirroring the SDF-5 stubs. Handles are enrolled through the
service's machine; the facilitator seat is opt-in.
"""

from __future__ import annotations

from types import SimpleNamespace

from tests.sdf5_stubs import THRASYMACHUS, justice_chain, make_service


def make_svc(tmp_path, *, mode: str = "participates", label: str = "sdf6-room",
             humans: tuple[str, ...] = ("Cephalus", "Polemarchus",
                                       "Thrasymachus"),
             facilitator: bool = False, allege: bool = True,
             claim: bool = True, claimant: str = "Thrasymachus") \
        -> SimpleNamespace:
    """A board on Justice with human handles, an original claim, and
    optionally one alleged 3a counterexample with its refutation Q.

    ``claimant`` defaults to Thrasymachus; 1-human-room tests pass a name
    inside ``humans`` so the room truly holds exactly one human.

    Returns a namespace: ``service``, ``board_id``, ``machine``, ``h``
    (display -> handle_id), ``f`` (facilitator handle or None), ``node``
    (the active claim node), ``ce`` / ``q`` (CE + refutation Q ids, or None).
    """
    service = make_service(tmp_path, chain=justice_chain())
    opened = service.open_board("Justice", label, mode=mode)
    bid = opened.board_id
    machine = service.machine(bid)
    h = {display: machine.enroll_handle(display) for display in humans}
    f = (machine.enroll_handle("facilitator", kind="enrolled",
                               is_facilitator=True) if facilitator else None)
    node = None
    if claim:
        node = service.claim_original(
            bid, THRASYMACHUS, claimant_display=claimant).node_id
    ce = q = None
    if allege and claim:
        alleged = service.allege(bid, "3a", by_display="Cephalus")
        ce, q = alleged.ce_id, alleged.q_id
    return SimpleNamespace(service=service, board_id=bid, machine=machine,
                           h=h, f=f, node=node, ce=ce, q=q)


__all__ = ["make_svc"]
