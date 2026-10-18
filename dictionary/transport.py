"""Injectable HTTP transport for the dictionary chain (stdlib urllib only).

HTTP status codes are *data* (``HttpResponse``); only connection-level
failures (DNS, timeout, refused) raise ``TransportError``. Sources
translate both into ``SourceOutcome`` records and never raise outward.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from urllib import error, request

USER_AGENT = "socratic-facilitator/0.1 (local self-hosted; contact recorded at deploy)"
DEFAULT_TIMEOUT = 5.0


class TransportError(Exception):
    """Connection-level failure (DNS, timeout, refused) — not an HTTP status."""


@dataclass
class HttpResponse:
    """A completed HTTP exchange; ``body`` is decoded with errors="replace"."""

    status: int
    body: str = ""
    url: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.body, (bytes, bytearray)):
            object.__setattr__(
                self, "body", bytes(self.body).decode("utf-8", errors="replace")
            )


@runtime_checkable
class Transport(Protocol):
    """Seam tests stub (``get`` style)."""

    def get(self, url: str) -> HttpResponse: ...


class UrllibTransport:
    """Default transport: urllib, one attempt, no retry/backoff by design."""

    def __init__(self, timeout: float = DEFAULT_TIMEOUT, user_agent: str = USER_AGENT) -> None:
        self.timeout = timeout
        self.user_agent = user_agent

    def get(
        self,
        url: str,
        timeout: float | None = None,
        headers: dict | None = None,
    ) -> HttpResponse:
        merged = {"User-Agent": self.user_agent, **dict(headers or {})}
        req = request.Request(url, headers=merged)
        try:
            with request.urlopen(req, timeout=self.timeout if timeout is None else timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return HttpResponse(status=resp.status, body=body, url=url)
        except error.HTTPError as exc:  # 4xx/5xx: status is data, not failure
            try:
                body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            except Exception:
                body = ""
            return HttpResponse(status=exc.code, body=body, url=url)
        except (error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise TransportError(f"{type(exc).__name__}: {exc}") from exc
