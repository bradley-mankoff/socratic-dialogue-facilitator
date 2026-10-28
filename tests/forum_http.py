"""Shared loopback HTTP helpers for the phone-forum tests.

One place for the way a person drives the forum over HTTP: serve one
forum on a free loopback port, fill in one start screen, tap Add a
player, open invitation links, GET a page, POST a form without following
the redirect, parse invitation links, and start many requests at the
same moment. ``test_symposium`` (start, join, instructions, first definition),
``test_phone_start`` (the host's start screen and players page) and
``test_concurrent_forum`` (two people at the same moment) drive the
same seam, so the serving fixture, the start fields and these
primitives live here once instead of copied in each test module.
Test-specific setup (how many guests, which names are expected) stays
in each test module.
"""

from __future__ import annotations

import contextlib
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from tests.sdf5_stubs import justice_chain, make_service
from web.forum import PLAYER_COLORS


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_get(url: str, timeout: float = 10, headers: dict | None = None):
    """GET a forum page: ``(status, body, url)``."""
    req = urllib.request.Request(url, headers=dict(headers or {}))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8"), resp.url


def http_get_noredirect(url: str, timeout: float = 10,
                        headers: dict | None = None):
    """GET a forum page without following a redirect.

    Returns ``(status, body, headers)`` so tests can assert the 303
    target of a guarded page (the host's players page opened with a
    guest's token) the way ``http_post_noredirect`` does for forms.
    """
    req = urllib.request.Request(url, headers=dict(headers or {}))
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8"), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8"), dict(exc.headers)


def http_post_noredirect(url: str, fields: dict, timeout: float = 10,
                         headers: dict | None = None):
    """POST a forum form without following the redirect.

    Returns ``(status, body, headers)`` so tests can assert the 303
    target or read the re-rendered form on a 200 refusal.
    """
    data = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers=dict(headers or {}))
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8"), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8"), dict(exc.headers)


_TOKEN_RE = re.compile(r'data-player="([A-Za-z0-9_-]+)"', re.S)


def invite_tokens(page: str) -> dict[str, str]:
    """``{player-N: token}`` parsed from Share messages in row order.

    Rows read Invited with no per-player names (players name themselves
    on arrival), so keys are positional; ``start_and_tokens`` maps the
    old familiar names onto these in invitation order."""
    tokens = list(dict.fromkeys(_TOKEN_RE.findall(page)))
    return {f"player-{n + 1}": token for n, token in enumerate(tokens)}


@contextlib.contextmanager
def serve(service):
    """One forum on a free loopback port; shut down on exit."""
    from web.forum import make_handler
    handler = make_handler(service)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.fixture
def live_forum(tmp_path):
    """One forum on a free loopback port over a stubbed dictionary chain."""
    service = make_service(tmp_path / "store", chain=justice_chain())
    with serve(service) as base:
        yield base, service


START_FIELDS = {
    "host_name": "Ada",
    "host_email": "ada@example.com",
    "symposium_name": "Friday Philosophers",
    "word": "Justice",
}
"""The one start screen: the host's own name and email, then the Settings
(the Symposium's name, the word, Anonymous Mode off by default).
``anonymous="on"`` turns Anonymous Mode on. No guest box: guests name
themselves on arrival."""


def start_fields(**overrides):
    """One start screen's fields, with per-test overrides."""
    fields = dict(START_FIELDS)
    fields.update(overrides)
    return fields


def start_symposium(base, **overrides):
    """POST one start screen: ``(status, page, headers)``."""
    return http_post_noredirect(base + "/start",
                                start_fields(**overrides))


def players_url_from(base, headers):
    """The host's players page from a Start redirect (absolute or not)."""
    location = headers.get("Location", "")
    return location if location.startswith("http") else base + location


def sid_from_players_url(players_url: str) -> str:
    """The Symposium id embedded in a players-page URL."""
    return players_url.split("/symposiums/")[1].split("/")[0]


def host_token_from_players_url(players_url: str) -> str:
    """The host token embedded in a players-page URL."""
    query = urllib.parse.urlsplit(players_url).query
    return urllib.parse.parse_qs(query)["token"][0]


def players_url(base, sid, token):
    """The host's players page URL, built in one place."""
    return base + f"/symposiums/{sid}/players?token={token}"


def share_button_messages(page: str) -> dict[str, str]:
    """``{token: server-built Share message}`` from each Share button."""
    import html as _html
    found: dict[str, str] = {}
    for tag in re.findall(r'<button[^>]*class="share"[^>]*>', page):
        person = re.search(r'data-player="([^"]+)"', tag)
        message = re.search(r'data-message="([^"]*)"', tag)
        assert person is not None and message is not None, tag
        found[person.group(1)] = _html.unescape(message.group(1))
    return found


def parse_start(base, headers):
    """The players page triple from a Start redirect's headers.

    Returns ``(players_url, host_token, sid)`` so tests that start
    with their own service (a custom dictionary chain) share the one
    parsing rule with ``start_on_players`` instead of rebuilding it."""
    players_url = players_url_from(base, headers)
    return (players_url, host_token_from_players_url(players_url),
            sid_from_players_url(players_url))


def start_on_players(base, **overrides):
    """Start and land on the host's players page.

    Returns ``(players_url, host_token, sid)``; asserts the 303 so a
    failed Start reads as the failed assumption it is.
    """
    status, page, headers = start_symposium(base, **overrides)
    assert status == 303, page[:500]
    players_page_url, host, sid = parse_start(base, headers)
    assert "/players" in players_page_url, players_page_url
    return (players_page_url, host, sid)


# The seven invited slots take the old familiar names in invitation order,
# so tests read like the people they stand for. The host keeps the name
# she typed on the start screen; guests name themselves on arrival in a
# later Bead, so until then only tokens tell them apart.
_SLOT_NAMES = ("Bohdan", "Cara", "Dara", "Elif", "Farah", "Gus",
               "Hana")


def start_and_tokens(base, guests: int = 2,
                     slot_names: tuple = _SLOT_NAMES, **overrides):
    """Start as the host, tap Add a player ``guests`` times.

    Returns ``(players page, tokens, sid)`` where ``tokens`` maps the old
    familiar names to tokens: Ada is the named host, the rest are the
    first ``guests`` names from ``slot_names`` in invitation order.
    Remaining keywords (``anonymous="on"``, ``word=...``) become the
    start screen's fields.
    """
    players_page_url, host, sid = start_on_players(base, **overrides)
    for _ in range(guests):
        add_player(base, sid, host)
    _, players_page, _ = http_get(players_page_url)
    slots = list(dict.fromkeys(invite_tokens(players_page).values()))
    assert len(slots) == guests, players_page[:2000]
    tokens = {"Ada": host}
    tokens.update({name: token
                   for name, token in zip(slot_names, slots)})
    return players_page, tokens, sid


def save_note(base, sid, host_token, player_token, note):
    """Keep the host's note to one invitee; expects the 303 back."""
    status, page, _headers = http_post_noredirect(
        base + f"/symposiums/{sid}/players/note",
        {"token": host_token, "player": player_token, "note": note})
    assert status == 303, page[:500]


def share_message(base, sid, host_token, player_token, note):
    """The server-built Share message for one player: ``(status, message)``.

    Posts the typed note the way the background note saver does (Accept:
    text/plain) so tests read the exact message the host shares or
    copies: the note, a line break, the personal link, or the link
    alone when the note is empty."""
    status, body, _headers = http_post_noredirect(
        base + f"/symposiums/{sid}/players/note",
        {"token": host_token, "player": player_token, "note": note},
        headers={"Accept": "text/plain"})
    return status, body


def add_player(base, sid, host_token):
    """One tap on Add a player; expects the 303 back to the players page."""
    status, page, _headers = http_post_noredirect(
        base + f"/symposiums/{sid}/players/add", {"token": host_token})
    assert status == 303, page[:500]


def claim(base, sid, token, original=None, sense=None):
    """One claim POST; returns ``(status, page, headers)`` without asserting.

    Callers that expect success assert the 303 themselves, so the same
    helper serves the phone-start and symposium tests (which expect 303)
    and the concurrent tests (where one of two simultaneous claims
    is refused with a 200)."""
    fields = {"token": token}
    if sense is not None:
        fields["sense"] = sense
    elif original is not None:
        fields["original"] = original
    return http_post_noredirect(base + f"/symposiums/{sid}/claim", fields)


def participant(service, sid, token):
    """One participant record from disk, matched by invitation token."""
    from server.symposium import SymposiumStore
    stored = SymposiumStore(service.root).get(sid)
    return next(p for p in stored["participants"] if p["token"] == token)


def join(base, token, *, name="", email="", color="", headers=None):
    """POST one arrival form; ``(status, page, headers)`` without asserting.

    Callers that expect success assert the 303 themselves, so the same
    helper serves the join tests (which expect 303) and the refusal tests
    (a taken name or color re-renders the form with a 200). ``headers``
    carries a cookie jar when one browser opens another person's link.
    """
    return http_post_noredirect(
        base + f"/join/{token}",
        {"name": name, "email": email, "color": color}, headers=headers)


def join_all(base, tokens):
    """Arrive everyone through the join flow (Bead sdf-zj6.3).

    Each guest joins with their slot name, a matching email and a
    distinct player color; the host picks their own color. Asserts each
    join's 303 the way the start helpers do, so a failed arrival reads
    as the failed assumption it is.
    """
    colors = [tint for _label, tint in PLAYER_COLORS]
    guests = [(name, token) for name, token in tokens.items()
              if name != "Ada"]
    for index, (name, token) in enumerate(guests):
        status, page, _ = join(
            base, token, name=name, email=f"{name.lower()}@example.com",
            color=colors[index % len(colors)])
        assert status == 303, (name, page[:500])
    if "Ada" in tokens:
        status, page, _ = join(
            base, tokens["Ada"], color=colors[len(guests) % len(colors)])
        assert status == 303, page[:500]


def enter(base, token, headers=None):
    """One tap on Go In; returns the Symposium-page redirect target."""
    status, page, resp_headers = http_post_noredirect(
        base + f"/join/{token}/enter", {}, headers=headers)
    assert status == 303, page[:500]
    return resp_headers.get("Location", "")


def visible(page: str) -> str:
    """The page's reading text: tags stripped, attributes gone."""
    return re.sub(r"<[^>]*>", " ", page)


def has_go_in_button(page: str) -> bool:
    """One Go In button, the way a person taps it."""
    return bool(re.search(r"<button[^>]*>[^<]*Go In[^<]*</button>", page))


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
    "http_get_noredirect",
    "http_post_noredirect",
    "invite_tokens",
    "run_at_once",
    "serve",
    "live_forum",
    "START_FIELDS",
    "start_fields",
    "start_symposium",
    "players_url_from",
    "sid_from_players_url",
    "host_token_from_players_url",
    "players_url",
    "share_button_messages",
    "parse_start",
    "start_on_players",
    "start_and_tokens",
    "add_player",
    "save_note",
    "share_message",
    "claim",
    "participant",
    "enter", "join", "join_all",
    "has_go_in_button",
    "visible",
]
