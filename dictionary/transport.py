"""Injectable HTTP transport for the dictionary chain (stdlib urllib only).

Fused (panels a+b+c): panel-a :class:`Transport` / :class:`UrllibTransport`
is canonical. Panel-b/c spellings (:class:`Fetch`, :class:`UrlLibFetch`,
``DEFAULT_USER_AGENT`` / ``DEFAULT_TIMEOUT``, :class:`SourceUnavailable` /
:class:`BadSourceResponse`) are aliases over the same behaviour so all
three import surfaces work.

HTTP status codes are *data* (``HttpResponse``); only connection-level
failures (DNS, timeout, refused) raise ``TransportError``. Sources
translate both into ``SourceOutcome`` records and never raise outward.
"""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable
from urllib import error, request

USER_AGENT = "socratic-facilitator/0.1 (local self-hosted; contact recorded at deploy)"
DEFAULT_USER_AGENT = USER_AGENT
DEFAULT_TIMEOUT = 5.0


class TransportError(Exception):
    """Connection-level failure (DNS, timeout, refused) — not an HTTP status."""


class DictionarySourceError(TransportError):
    """Panel-c base for source failures (transport-level)."""

    def __init__(
        self,
        message: str,
        *,
        source: str | None = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.source = source
        self.http_status = http_status

    @property
    def detail(self) -> str:
        return str(self)


class SourceUnavailable(DictionarySourceError):
    """Panel-c: the vote could not be consulted (transport failure / 5xx)."""


class BadSourceResponse(DictionarySourceError):
    """Panel-c: the source replied, but not with its documented payload."""


@dataclass
class HttpResponse:
    """A completed HTTP exchange; ``body`` is decoded with errors="replace"."""

    status: int
    body: str = ""
    url: str = ""

    def __post_init__(self) -> None:
        # Panel-b stubs hand back ``bytes``; normalise to ``str`` once.
        if isinstance(self.body, (bytes, bytearray)):
            object.__setattr__(
                self, "body", bytes(self.body).decode("utf-8", errors="replace")
            )

    @property
    def ok(self) -> bool:
        """Panel-c: True for 2xx."""
        return 200 <= self.status < 300

    @property
    def server_error(self) -> bool:
        """Panel-c: True for 5xx."""
        return self.status >= 500

    def json(self, *, source: str | None = None) -> Any:
        """Decode the body, or raise :class:`BadSourceResponse` (panel c)."""
        try:
            return json.loads(self.body)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            snippet = (self.body or "").strip().replace("\n", " ")[:80]
            raise BadSourceResponse(
                f"expected JSON from {source or 'source'} but could not decode it "
                f"({exc}); body started {snippet!r}",
                source=source,
                http_status=self.status,
            ) from exc


@runtime_checkable
class Transport(Protocol):
    """Seam tests stub and SDF-16 reuses (``get`` style, panel a)."""

    def get(self, url: str) -> HttpResponse: ...


@runtime_checkable
class Fetch(Protocol):
    """Callable seam (panel c): ``fetch(url) -> HttpResponse``."""

    def __call__(self, url: str) -> HttpResponse: ...  # pragma: no cover - protocol


class UrllibTransport:
    """Default transport: urllib, one attempt, no retry/backoff by design.

    Supports both ``get(url)`` (panel a/b) and ``__call__(url)`` (panel c).
    """

    def __init__(self, timeout: float = DEFAULT_TIMEOUT, user_agent: str = USER_AGENT) -> None:
        self.timeout = timeout
        self.user_agent = user_agent

    def get(self, url: str, timeout: float | None = None) -> HttpResponse:
        req = request.Request(url, headers={"User-Agent": self.user_agent})
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

    def __call__(self, url: str) -> HttpResponse:
        return self.get(url)


# Panel-b/c alias: the same stdlib transport under its second name.
UrlLibFetch = UrllibTransport
