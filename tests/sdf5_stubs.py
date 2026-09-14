"""SDF-5 stub helpers: a Justice dictionary chain with zero live HTTP.

No pytest import here (mirrors ``tests/stubs.py``) so any module can use it.
One :class:`StubTransport` counts calls, which is how the shared-cache
acceptance criterion is proved: two boards on ``Justice`` must cost exactly
the two source calls of one board.
"""

from __future__ import annotations

from pathlib import Path

from dictionary.chain import build_default_chain
from tests.stubs import StubTransport, json_response

DATE = "2026-09-13"
TS = "2026-09-13T00:00:00+00:00"

# Measured order for the two Justice fixtures: distinct-sources first, then
# stability, then article order (see tests/test_chain_http.py).
S0 = "The fair and honest administration of the law by individuals."
S1 = "A judge of a court of law."
S2 = "The fair and honest administration of the law by courts."
THRASYMACHUS = "Justice is the advantage of the stronger."
CEPHALUS = "Justice is paying your debts and telling the truth."

JUSTICE = "Justice"
REPUBLIC = "Justice (Republic Book I)"


def justice_stub() -> StubTransport:
    """Both default sources answering for Justice."""
    return StubTransport({
        "en.wiktionary.org": json_response("wiktionary_justice.json"),
        "dictionaryapi.dev": json_response("freedict_justice.json"),
    })


def empty_stub() -> StubTransport:
    """Both sources reachable but with no entry: the chain's empty state."""
    missing = json_response("wiktionary_missing.json")
    return StubTransport({
        "en.wiktionary.org": missing,
        "dictionaryapi.dev": missing,
    })


def justice_chain(stub: StubTransport | None = None):
    """Default Wiktionary + Free Dictionary chain over a stub, fixed clock."""
    return build_default_chain(stub if stub is not None else justice_stub(),
                              clock=lambda: DATE)


def empty_chain(stub: StubTransport | None = None):
    return build_default_chain(stub if stub is not None else empty_stub(),
                              clock=lambda: DATE)


def fixed_clock() -> callable:
    return lambda: TS


def make_service(root: Path | str, chain=None, clock=None):
    """A :class:`BoardService` on ``root`` with a stubbed chain + fixed clock.

    The chain instance is shared by the whole service, so ``stub.calls`` is
    the authoritative count of canonical pulls for that data home.
    """
    from server.service import BoardService

    stub = chain is None
    if stub:
        chain = justice_chain()
    return BoardService(root, chain=chain, clock=clock or fixed_clock())


def service_stub(service):
    """The transport a ``make_service`` chain was built over (for call counts)."""
    return service.chain.transport


__all__ = [
    "DATE", "TS", "S0", "S1", "S2", "THRASYMACHUS", "CEPHALUS",
    "JUSTICE", "REPUBLIC",
    "justice_stub", "empty_stub", "justice_chain", "empty_chain",
    "fixed_clock", "make_service", "service_stub",
]
