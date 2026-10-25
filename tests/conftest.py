"""Shared fixtures for the SDF-2 headless verdict suite."""

import urllib.parse
import urllib.request
from types import SimpleNamespace

import pytest

from board.machine import VerdictMachine

CLAIM = "Justice is the advantage of the stronger."


@pytest.fixture
def make_env():
    """Factory for a fresh in-memory board.

    Enrolls ``humans`` (default h1..h3), registers active node ``n1``
    and attaches one counterexample ``ce1``
    with its refutation Q ``q1`` (opened by the first human).
    """

    def _make(humans=("h1", "h2", "h3"), medium="async"):
        m = VerdictMachine.in_memory(medium=medium)
        h = {name: m.enroll_handle(name) for name in humans}
        n = m.register_node("n1", CLAIM)
        ce, q = m.open_refutation_q(n, "3a", opened_by=h[humans[0]])
        return SimpleNamespace(machine=m, h=h, node=n, ce=ce, q=q)

    return _make


_ORIGINAL_URLOPEN = urllib.request.urlopen


def _is_loopback(url) -> bool:
    target = url.full_url if hasattr(url, "full_url") else str(url)
    host = urllib.parse.urlsplit(target).hostname or ""
    return host in ("127.0.0.1", "localhost", "::1")


@pytest.fixture(autouse=True)
def no_live_network(monkeypatch):
    """SDF-3: block real network calls; loopback transport tests still run."""

    def guarded(url, *args, **kwargs):
        if not _is_loopback(url):
            raise AssertionError(f"tests must not touch the live network: {url!r}")
        return _ORIGINAL_URLOPEN(url, *args, **kwargs)

    monkeypatch.setattr(urllib.request, "urlopen", guarded)
    yield


# ---------------------------------------------------------------------------
# SDF-5 — board operations (registry + canonical cache + claim/revise).
# Everything is stubbed: no live HTTP, no shared fixtures with earlier suites.
# ---------------------------------------------------------------------------


@pytest.fixture
def sdf5_store(tmp_path):
    """Fresh data root for one service."""
    return tmp_path / "store"


@pytest.fixture
def sdf5_stub():
    """Counting transport over the Justice fixtures."""
    from tests.sdf5_stubs import justice_stub

    return justice_stub()


@pytest.fixture
def sdf5_svc(sdf5_store, sdf5_stub):
    """Board service over the stubbed chain with a deterministic clock."""
    from tests.sdf5_stubs import make_service

    return make_service(sdf5_store, chain=_sdf5_chain(sdf5_stub))


def _sdf5_chain(stub):
    from dictionary.chain import build_default_chain

    return build_default_chain(stub, clock=lambda: "2026-09-13")


HUMAN_DISPLAYS = ("Cephalus", "Polemarchus", "Thrasymachus")


@pytest.fixture
def sdf5_open(sdf5_svc):
    """Board ``justice`` with three human handles already enrolled."""
    opened = sdf5_svc.open_board("Justice")
    machine = sdf5_svc.machine(opened.board_id)
    handles = {display: machine.enroll_handle(display) for display in HUMAN_DISPLAYS}
    return SimpleNamespace(
        service=sdf5_svc, board_id=opened.board_id, record=opened.record,
        view=opened.view, machine=machine, h=handles,
    )