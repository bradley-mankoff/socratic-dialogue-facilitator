"""SDF-18 share URLs: one Quick Tunnel command plus QR LAN fallback.

Stdlib only, pure functions — no I/O, no network, no third party. A share
URL is *computed*, never stored: board identity stays ``(X, label)`` in the
registry, so rotating the URL can never rename a board (story 41).

URL kinds (per the host-substrate research):

* ``quick`` — Cloudflare Quick Tunnel: one command, no account, public
  HTTPS ``*.trycloudflare.com``. Rotates every run (new random subdomain,
  dies with the process), dev/test SLA only, no SSE (use WebSocket/poll).
* ``lan`` — same-WiFi fallback ``http://<lan-ip>:PORT``: zero third
  parties, lowest latency. DHCP-unstable, LAN-only, plain HTTP.
* ``localhost`` — last-resort screen-share fallback; guests are view-only.
* ``named`` — a named-tunnel public HTTPS host: the ONLY kind that can
  carry a stable-public-URL promise, and only when the caller passes
  ``named_tunnel=True`` (an account + named tunnel exist).
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

QUICK_TUNNEL_SUFFIX = ".trycloudflare.com"
QUICK_TUNNEL_HOST_RE = re.compile(r"^[a-z0-9-]+\.trycloudflare\.com$")


def quick_tunnel_command(port: int) -> str:
    """The one share command: serve locally, print the tunnel URL from it."""
    _check_port(port)
    return f"cloudflared tunnel --url http://localhost:{port}"


def lan_url(host: str, port: int) -> str:
    """Same-WiFi fallback URL. Pure string build — zero third parties, zero
    network calls: the caller supplies the Mac's LAN IP (or ``*.local``
    Bonjour name) and this function never resolves, fetches, or phones
    anything."""
    if not isinstance(host, str) or not host.strip():
        raise ValueError("lan host must be a non-blank IP or .local name")
    host = host.strip()
    if any(ch.isspace() for ch in host) or "://" in host:
        raise ValueError(f"lan host must be a bare host, not {host!r}")
    _check_port(port)
    return f"http://{host}:{port}"


def qr_payload(url: str) -> str:
    """What the fallback QR encodes: the URL verbatim.

    Deliberately a string, not an image — v1 ships no QR dependency. Any
    QR printer (phone camera, ``qrencode``) turns this payload into a
    joinable code; the joinability property is that the payload IS the URL.
    """
    if not isinstance(url, str) or not url.strip():
        raise ValueError("qr payload needs a non-blank URL")
    return url.strip()


def classify_url(url: str) -> str:
    """``quick`` | ``lan`` | ``localhost`` | ``named`` | ``unknown``."""
    try:
        parts = urlsplit(str(url).strip())
    except ValueError:
        return "unknown"
    host = (parts.hostname or "").lower()
    scheme = parts.scheme.lower()
    if not host:
        return "unknown"
    if QUICK_TUNNEL_HOST_RE.match(host):
        return "quick"
    if host in ("localhost", "127.0.0.1", "::1"):
        return "localhost"
    if scheme == "http":
        return "lan"
    if scheme == "https":
        return "named"
    return "unknown"


def is_stable_public(url: str, *, named_tunnel: bool = False) -> bool:
    """Whether a stable public URL may be promised for ``url``.

    Only a named-tunnel HTTPS host counts, and only when the caller confirms
    the named tunnel exists (``named_tunnel=True``). Quick Tunnel URLs
    rotate every run, LAN URLs are DHCP-unstable and LAN-only, localhost
    never leaves the Mac — all refuse, with or without the flag.
    """
    if not named_tunnel:
        return False
    return classify_url(url) == "named"


def share_info(url: str, *, named_tunnel: bool = False) -> dict:
    """Joinable-URL report: ``{url, kind, stable, note}``. JSON-able."""
    kind = classify_url(url)
    stable = is_stable_public(url, named_tunnel=named_tunnel)
    if kind == "quick":
        note = ("Rotating Quick Tunnel URL (new subdomain per run, dies "
                "with the process; dev/test SLA only, no SSE — "
                "use WebSocket/poll). Re-print/re-QR each session.")
    elif kind == "lan":
        note = ("Same-WiFi LAN fallback: zero third parties, lowest "
                "latency. DHCP-unstable (prefer the .local name); "
                "LAN-only, plain HTTP.")
    elif kind == "localhost":
        note = ("Localhost fallback: no URL for guests; host drives over "
                "screen-share, guests are view-only.")
    elif stable:
        note = "Named tunnel: stable public URL."
    else:
        note = ("No stable public URL is promised without a named tunnel.")
    return {"url": url, "kind": kind, "stable": bool(stable), "note": note}


def rejoin_url(current_url: str) -> str:
    """Guests rejoin on whatever the current URL is (story 41).

    Identity lives in ``(X, label)``, not in this string — after sleep or a
    crash the host re-prints the (possibly rotated) URL and every guest
    rejoins on it; no re-enrollment, no new board.
    """
    if not isinstance(current_url, str) or not current_url.strip():
        raise ValueError("rejoin needs the current non-blank share URL")
    return current_url.strip()


def _check_port(port: int) -> int:
    if not isinstance(port, int) or isinstance(port, bool):
        raise ValueError(f"port must be an int, not {port!r}")
    if not 1 <= port <= 65535:
        raise ValueError(f"port must be 1..65535, not {port!r}")
    return port


__all__ = [
    "QUICK_TUNNEL_SUFFIX",
    "quick_tunnel_command",
    "lan_url",
    "qr_payload",
    "classify_url",
    "is_stable_public",
    "share_info",
    "rejoin_url",
]
