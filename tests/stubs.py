"""SDF-3 stubbed transport and fixture loader. No pytest import needed."""

from __future__ import annotations

import json
import pathlib
from typing import Any

from dictionary.transport import HttpResponse

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


class StubTransport:
    """Map URL substring -> HttpResponse to return or Exception to raise.

    Keys must match exactly one substring of the request URL (asserts if
    ambiguous). Records every requested URL in ``self.calls`` so cache tests
    can assert on transport traffic.
    """

    def __init__(self, responses: dict) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str) -> HttpResponse:
        self.calls.append(url)
        matches = [key for key in self.responses if key in url]
        assert len(matches) == 1, f"ambiguous stub for {url}: {matches}"
        mapped = self.responses[matches[0]]
        if isinstance(mapped, Exception):
            raise mapped
        return mapped


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def json_response(name: str, status: int = 200, url: str = "") -> HttpResponse:
    """Wrap a fixture file as a JSON response for ``StubTransport``."""
    return HttpResponse(
        status=status, body=json.dumps(load_fixture(name)), url=url
    )
