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