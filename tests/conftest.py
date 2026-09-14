"""Shared fixtures for the SDF-2 headless verdict suite."""

from types import SimpleNamespace

import pytest

from board.machine import VerdictMachine

CLAIM = "Justice is the advantage of the stronger."


@pytest.fixture
def make_env():
    """Factory for a fresh in-memory board.

    Enrolls ``humans`` (default h1..h3), optionally a facilitator handle,
    registers active node ``n1`` and attaches one counterexample ``ce1``
    with its refutation Q ``q1`` (opened by the first human).
    """

    def _make(humans=("h1", "h2", "h3"), mode="participates",
              facilitator=False, medium="async"):
        m = VerdictMachine.in_memory(mode=mode, medium=medium)
        h = {name: m.enroll_handle(name) for name in humans}
        f = None
        if facilitator:
            f = m.enroll_handle("facilitator", kind="enrolled",
                                is_facilitator=True)
        n = m.register_node("n1", CLAIM)
        ce, q = m.open_refutation_q(n, "3a", opened_by=h[humans[0]])
        return SimpleNamespace(machine=m, h=h, f=f, node=n, ce=ce, q=q)

    return _make