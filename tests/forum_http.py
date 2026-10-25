"""Shared loopback HTTP helpers for the phone-forum tests.

One place for the way a person drives the forum over HTTP: GET a page,
POST a form without following the redirect, parse invitation links, and
start many requests at the same moment. Both ``test_symposium`` (start,
welcome, first definition) and ``test_concurrent_forum`` (two people at
the same moment) drive the same seam, so they share these primitives
instead of copying them. Test-specific setup (which guests start a
Symposium, which names are expected) stays in each test module.
"""

from __future__ import annotations

import re
import threading
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_get(url: str, timeout: float = 10):
    """GET a forum page: ``(status, body, url)``."""
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8"), resp.url


def http_post_noredirect(url: str, fields: dict, timeout: float = 10):
    """POST a forum form without following the redirect.

    Returns ``(status, body, headers)`` so tests can assert the 303
    target or read the re-rendered form on a 200 refusal.
    """
    data = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8"), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8"), dict(exc.headers)


_TOKEN_RE = re.compile(
    r'<li[^>]*>\s*<span class="who">([^<]+)</span>.*?/join/([A-Za-z0-9_-]+)',
    re.S,
)


def invite_tokens(page: str) -> dict[str, str]:
    """``{name: token}`` parsed from invitation rows (name beside its link)."""
    return {name.strip(): token for name, token in _TOKEN_RE.findall(page)}


def run_at_once(calls: dict):
    """Start every callable at the same moment; return results and errors."""
    barrier = threading.Barrier(len(calls))
    results: dict = {}
    errors: list = []

    def _wrap(key, func):
        try:
            barrier.wait(timeout=10)
            results[key] = func()
        except Exception as exc:  # never let a thread die silently
            errors.append(exc)

    threads = [
        threading.Thread(target=_wrap, args=(key, func))
        for key, func in calls.items()
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    return results, errors


__all__ = [
    "NoRedirect",
    "http_get",
    "http_post_noredirect",
    "invite_tokens",
    "run_at_once",
]
