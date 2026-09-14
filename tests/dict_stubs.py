"""Panel-b/c import alias: route-table stubs over :mod:`tests.stubs`.

Both spellings work: ``StubTransport`` (substring map, panel a) and
``FakeTransport`` (prefix routes, panel b) share the same record-calls
contract. ``chain_with`` builds a default chain with a fixed clock.
"""

from __future__ import annotations

from tests.stubs import StubTransport, json_response, load_fixture

from dictionary.chain import build_default_chain
from dictionary.transport import HttpResponse


class FakeTransport(StubTransport):
    """Substring/prefix stub with ``calls_to`` helper (panel b)."""

    def calls_to(self, fragment: str) -> list[str]:
        return [call for call in self.calls if fragment in call]


def chain_with(stub, clock_value: str = "2026-09-13", **kwargs):
    """Default chain with an injectable fixed clock."""
    return build_default_chain(stub, clock=lambda: clock_value, **kwargs)


__all__ = [
    "FakeTransport",
    "StubTransport",
    "HttpResponse",
    "json_response",
    "load_fixture",
    "chain_with",
]
