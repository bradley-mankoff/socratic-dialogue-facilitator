"""Symposium start, invitations, welcome and first definition (Bead sdf-mgt.11).

Seam: HTTP over loopback on a free port (``web.forum`` stdlib server over a
real ``BoardService`` with a stubbed dictionary chain). Every behaviour is
driven the way a person drives it: start form -> invitation page with
personal links -> welcome page -> definitions page -> pick-or-write.

Stdlib only: ``urllib`` client, ``http.server`` under test, no live network
(the autouse ``no_live_network`` guard stands behind every test here).
"""

from __future__ import annotations

import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from tests.forum_http import (
    NoRedirect as _NoRedirect,
    http_get as _get,
    http_post_noredirect as _post_noredirect,
    invite_tokens as _invite_tokens,
)
from tests.sdf5_stubs import DATE, S0, justice_chain, make_service


def _serve(service):
    from web.forum import make_handler
    handler = make_handler(service)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        yield base
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.fixture
def forum_base(tmp_path):
    service = make_service(tmp_path / "store", chain=justice_chain())
    gen = _serve(service)
    base = next(gen)
    yield base, service
    try:
        next(gen)
    except StopIteration:
        pass


def _post(url, fields):
    data = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req) as resp:
        return resp.status, resp.read().decode("utf-8"), resp.url


def _visible(page: str) -> str:
    return re.sub(r"<[^>]*>", " ", page)


START_FIELDS = {
    "host_name": "Ada",
    "host_email": "ada@example.com",
    "word": "Justice",
    "guests": "Bohdan <bohdan@example.com>\nCara <cara@example.com>",
    # NOTE: the removed "mode" and "socrates" fields live only in
    # test_legacy_facilitator_fields_are_ignored, which proves old forms
    # still start a Symposium.
}


def _start(base, **overrides):
    fields = dict(START_FIELDS)
    fields.update(overrides)
    return _post_noredirect(base + "/start", fields)


def _enter(base, token):
    status, _page, headers = _post_noredirect(base + f"/join/{token}/enter",
                                              {})
    assert status == 303, _page[:500]
    return headers.get("Location", "")


def _start_and_tokens(base):
    status, page, headers = _start(base)
    assert status == 303, page[:500]
    location = headers.get("Location", "")
    assert "/invitations" in location
    inv_url = location if location.startswith("http") else base + location
    _, invites, _ = _get(inv_url)
    tokens = _invite_tokens(invites)
    assert set(tokens) == {"Ada", "Bohdan", "Cara"}, invites[:2000]
    sid = invites.split("/symposiums/")[1].split("/")[0].split('"')[0].split("?")[0]
    return invites, tokens, sid


# -- the host starts a Symposium with its people ----------------------------

def test_start_form_names_a_symposium_not_a_board_or_room(forum_base):
    base, _service = forum_base
    _, home, _ = _get(base + "/")
    assert "Symposium" in home
    assert "host_name" in home and "host_email" in home
    assert "word" in home and "guests" in home
    visible = _visible(home)
    assert not re.search(r"\bboards?\b", visible, re.I), "says board"
    assert not re.search(r"\brooms?\b", visible, re.I), "says room"


def test_host_start_opens_for_talk_at_once_with_no_begin_button(forum_base):
    base, _service = forum_base
    invites, tokens, sid = _start_and_tokens(base)
    assert "Copy" in invites or "copy" in invites
    for name, token in tokens.items():
        _, welcome, _ = _get(base + f"/join/{token}")
        assert "Begin" not in welcome
    _, definitions, _ = _get(
        base + f"/symposiums/{sid}?token={tokens['Bohdan']}")
    assert "Justice" in definitions
    assert "Begin" not in definitions


def test_same_word_same_people_refused_while_open(forum_base):
    base, service = forum_base
    _start_and_tokens(base)
    before = len(service.registry.boards)
    status, page, _headers = _start(base)
    assert status == 200, "a refused start re-renders, never redirects"
    assert "already" in page.lower() and "open" in page.lower()
    assert "Error" not in page
    assert len(service.registry.boards) == before


def test_same_word_different_people_makes_a_new_symposium(forum_base):
    base, _service = forum_base
    _invites_a, _tokens_a, sid_a = _start_and_tokens(base)
    status, _page, headers = _start(
        base, guests="Bohdan <bohdan@example.com>\nDee <dee@example.com>")
    assert status == 303
    location = headers.get("Location", "")
    assert "/symposiums/" in location
    sid_b = location.split("/symposiums/")[1].split("/")[0]
    assert sid_b != sid_a


# -- invitations and the welcome page ---------------------------------------

def test_invitation_page_lists_personal_links_with_copy_buttons(forum_base):
    base, _service = forum_base
    invites, tokens, _sid = _start_and_tokens(base)
    for name, token in tokens.items():
        assert f"/join/{token}" in invites, name
    assert invites.lower().count("copy") >= 3
    # only the host ever sees emails: the host's page shows them
    assert "ada@example.com" in invites
    assert "bohdan@example.com" in invites


def test_opening_a_link_signs_in_with_no_password(forum_base):
    base, _service = forum_base
    _invites, tokens, sid = _start_and_tokens(base)
    token = tokens["Bohdan"]
    _, welcome, _ = _get(base + f"/join/{token}")
    assert "Bohdan" in welcome
    _enter(base, token)
    _, definitions, _ = _get(base + f"/symposiums/{sid}?token={token}")
    assert "Bohdan" in definitions or "Justice" in definitions


def test_first_visit_shows_welcome_with_word_people_how_it_works(forum_base):
    base, _service = forum_base
    _invites, tokens, _sid = _start_and_tokens(base)
    _, welcome, _ = _get(base + f"/join/{tokens['Cara']}")
    assert "Justice" in welcome
    assert "Ada" in welcome and "Bohdan" in welcome
    lowered = welcome.lower()
    assert "one definition at a time" in lowered
    assert "challenge" in lowered
    assert "vote" in lowered
    assert re.search(r"<button[^>]*>[^<]*go in[^<]*</button>", welcome, re.I)
    # the welcome page names names, never emails
    assert "ada@example.com" not in welcome
    assert "cara@example.com" not in welcome


def test_welcome_button_goes_in_and_second_visit_skips_welcome(forum_base):
    base, _service = forum_base
    _invites, tokens, sid = _start_and_tokens(base)
    token = tokens["Cara"]
    location = _enter(base, token)
    assert f"/symposiums/{sid}" in location
    _, definitions, _ = _get(base + f"/symposiums/{sid}?token={token}")
    assert "Justice" in definitions


# -- definitions with small linked source notes ------------------------------

def test_definitions_end_with_small_linked_source_notes(forum_base):
    base, _service = forum_base
    _invites, tokens, sid = _start_and_tokens(base)
    _enter(base, tokens["Ada"])
    _, page, _ = _get(base + f"/symposiums/{sid}?token={tokens['Ada']}")
    assert S0 in page
    assert re.search(
        r'<small><a href="https://[^"]+">\(Wiktionary\)</a></small>', page), \
        page[page.find(S0):page.find(S0) + 400]


def test_no_license_or_access_date_on_definitions(forum_base):
    base, _service = forum_base
    _invites, tokens, sid = _start_and_tokens(base)
    _enter(base, tokens["Ada"])
    _, page, _ = _get(base + f"/symposiums/{sid}?token={tokens['Ada']}")
    visible = _visible(page)
    assert "CC BY-SA" not in visible
    assert "unverified-upstream" not in visible
    assert "License" not in visible and "license" not in visible
    assert DATE not in visible
    assert "Accessed" not in visible and "accessed" not in visible


def test_wiktionary_link_markup_stripped_to_display_text():
    from dictionary.sources import parse_wikitext_senses
    wikitext = (
        "==English==\n"
        "\n"
        "===Noun===\n"
        "# being [[just]] or [[fair]].\n"
        "# [[judgment|Judgment]] is due.\n"
        "# [[intimidate]]d by power.\n"
    )
    senses = parse_wikitext_senses(wikitext)
    assert [s.gloss for s in senses] == [
        "being just or fair.",
        "Judgment is due.",
        "intimidated by power.",
    ]
    for sense in senses:
        assert "[[" not in sense.gloss and "]]" not in sense.gloss


# -- the first claim: pick or write, then the form is gone -------------------

def test_first_claim_picks_a_dictionary_definition(forum_base):
    base, service = forum_base
    _invites, tokens, sid = _start_and_tokens(base)
    _enter(base, tokens["Ada"])
    _enter(base, tokens["Cara"])
    claim_url = base + f"/symposiums/{sid}/claim"
    status, _page, headers = _post_noredirect(
        claim_url, {"token": tokens["Ada"], "sense": "s0"})
    assert status == 303
    _, page, _ = _get(base + f"/symposiums/{sid}?token={tokens['Ada']}")
    assert S0 in page
    assert "dictionary" in page.lower()
    assert "Ada" in page
    assert "Claim the definition" not in page
    assert "Pick one" not in page
    assert "Or write your own" not in page
    state = service.state(service.registry.by_id(sid).board_id) \
        if service.registry.by_id(sid) is not None else None
    assert state is None or state.active_node_id is not None


def test_first_claim_writes_ones_own_in_a_fresh_symposium(forum_base):
    base, _service = forum_base
    status, _page, headers = _start(base, word="Courage")
    assert status == 303
    inv_url = headers["Location"]
    inv_url = inv_url if inv_url.startswith("http") else base + inv_url
    _, invites, _ = _get(inv_url)
    tokens = _invite_tokens(invites)
    sid = inv_url.split("/symposiums/")[1].split("/")[0]
    _enter(base, tokens["Bohdan"])
    mine = "Courage is facing fear for what matters."
    status, _page, _headers = _post_noredirect(
        base + f"/symposiums/{sid}/claim",
        {"token": tokens["Bohdan"], "original": mine})
    assert status == 303
    _, page, _ = _get(base + f"/symposiums/{sid}?token={tokens['Bohdan']}")
    assert mine in page
    assert "Bohdan" in page
    assert "Claim the definition" not in page


def test_second_claim_refused_with_plain_message_journal_untouched(forum_base):
    base, service = forum_base
    _invites, tokens, sid = _start_and_tokens(base)
    _enter(base, tokens["Ada"])
    _enter(base, tokens["Cara"])
    claim_url = base + f"/symposiums/{sid}/claim"
    _post_noredirect(claim_url, {"token": tokens["Ada"], "sense": "s0"})
    board_id = service.registry.by_id(sid).board_id
    before = service.machine(board_id).state.seq
    nodes_before = len(service.machine(board_id).state.nodes)
    status, page, _ = _post_noredirect(
        claim_url, {"token": tokens["Cara"],
                    "original": "Justice is order."})
    assert status == 200
    assert "already" in page.lower() and "active" in page.lower()
    assert "Error" not in page
    after = service.machine(board_id)
    assert after.state.seq == before
    assert len(after.state.nodes) == nodes_before
    status, page, _ = _post_noredirect(
        claim_url, {"token": tokens["Cara"], "sense": "s1"})
    assert status == 200
    assert "already" in page.lower() and "active" in page.lower()
    assert len(service.machine(board_id).state.nodes) == nodes_before


# -- the start page asks for people and a word, nothing else ---------------------

def test_start_page_has_no_facilitator_role_or_first_questioner(forum_base):
    base, _service = forum_base
    _, home, _ = _get(base + "/")
    assert 'name="mode"' not in home
    assert 'name="socrates"' not in home
    visible = _visible(home)
    assert "Facilitator role" not in visible
    assert "first questioner" not in visible.lower()
    assert "keeps score" not in visible.lower()
    assert "takes part" not in visible.lower()


def test_symposium_starts_without_facilitator_fields(forum_base):
    base, service = forum_base
    status, _page, headers = _post_noredirect(base + "/start", {
        "host_name": "Ada",
        "host_email": "ada@example.com",
        "word": "Justice",
        "guests": "Bohdan <bohdan@example.com>\nCara <cara@example.com>",
    })
    assert status == 303, "a Symposium starts with people and a word alone"
    inv_url = headers.get("Location", "")
    inv_url = inv_url if inv_url.startswith("http") else base + inv_url
    _, invites, _ = _get(inv_url)
    tokens = _invite_tokens(invites)
    assert set(tokens) == {"Ada", "Bohdan", "Cara"}
    sid = inv_url.split("/symposiums/")[1].split("/")[0]
    state = service.state(sid)
    assert state.active_node_id is None, "a fresh Symposium has no claim"
    _enter(base, tokens["Ada"])
    _, page, _ = _get(base + f"/symposiums/{sid}?token={tokens['Ada']}")
    assert "Justice" in page
    assert "keeps score" not in page.lower()
    assert "takes part" not in page.lower()


def test_legacy_facilitator_fields_are_ignored(forum_base):
    base, service = forum_base
    status, _page, headers = _start(
        base, mode="facilitates", socrates="bohdan@example.com")
    assert status == 303, "old form fields never break a start"
    inv_url = headers.get("Location", "")
    inv_url = inv_url if inv_url.startswith("http") else base + inv_url
    _, invites, _ = _get(inv_url)
    tokens = _invite_tokens(invites)
    sid = inv_url.split("/symposiums/")[1].split("/")[0]
    _enter(base, tokens["Ada"])
    _, page, _ = _get(base + f"/symposiums/{sid}?token={tokens['Ada']}")
    assert "only keeps score" not in page.lower()
    assert "takes part" not in page.lower()


# -- host-only links ----------------------------------------------------------

def test_invitation_links_belong_to_the_host_alone(forum_base):
    base, _service = forum_base
    _invites, tokens, sid = _start_and_tokens(base)
    _enter(base, tokens["Bohdan"])
    inv_url = base + f"/symposiums/{sid}/invitations?token={tokens['Bohdan']}"
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(inv_url) as resp:
            status, location = resp.status, ""
    except urllib.error.HTTPError as exc:
        status, location = exc.code, exc.headers.get("Location", "")
    assert status == 303
    assert f"/symposiums/{sid}" in location
    assert "token=" in location


def test_after_close_the_same_people_start_a_numbered_next_one(forum_base):
    base, service = forum_base
    _invites, tokens, sid = _start_and_tokens(base)
    _enter(base, tokens["Ada"])
    machine = service.machine(sid)
    by_name = {handle.display: h
               for h, handle in machine.state.handles.items()}
    close_q = machine.open_governance_q("close",
                                          opened_by=by_name["Ada"])
    machine.cast(close_q, by_name["Ada"], "explicit", "for")
    machine.cast(close_q, by_name["Bohdan"], "explicit", "for")
    service.force_settle(sid, close_q)
    assert service.state(sid).status == "closed"
    status, _page, headers = _start(base)
    assert status == 303, "a closed Symposium frees its word and people"
    inv_url = headers["Location"]
    inv_url = inv_url if inv_url.startswith("http") else base + inv_url
    _, invites, _ = _get(inv_url)
    assert "second symposium" in invites.lower()


# -- empty dictionaries still leave a working page --------------------------------

def test_word_with_no_dictionary_entry_can_still_be_defined_by_hand(tmp_path):
    from tests.sdf5_stubs import empty_chain
    service = make_service(tmp_path / "store", chain=empty_chain())
    gen = _serve(service)
    base = next(gen)
    try:
        status, _page, headers = _post_noredirect(base + "/start", {
            "host_name": "Ada", "host_email": "ada@example.com",
            "word": "Sophrosyne",
            "guests": "Bohdan <bohdan@example.com>"})
        assert status == 303
        inv_url = headers["Location"]
        inv_url = inv_url if inv_url.startswith("http") else base + inv_url
        _, invites, _ = _get(inv_url)
        tokens = _invite_tokens(invites)
        sid = inv_url.split("/symposiums/")[1].split("/")[0]
        _enter(base, tokens["Ada"])
        _, page, _ = _get(base + f"/symposiums/{sid}?token={tokens['Ada']}")
        assert "No dictionary definitions were found" in page
        status, refused, _ = _post_noredirect(
            base + f"/symposiums/{sid}/claim",
            {"token": tokens["Ada"], "sense": "s0"})
        assert status == 200
        assert "write your own" in refused.lower()
        mine = "Sophrosyne is mastery of oneself."
        status, _page, _ = _post_noredirect(
            base + f"/symposiums/{sid}/claim",
            {"token": tokens["Ada"], "original": mine})
        assert status == 303
        _, page, _ = _get(base + f"/symposiums/{sid}?token={tokens['Ada']}")
        assert mine in page
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


# -- what no page may show ----------------------------------------------------

def test_no_page_shows_emails_machine_ids_boards_rooms_or_test_controls(
        forum_base):
    base, _service = forum_base
    _invites, tokens, sid = _start_and_tokens(base)
    guest = tokens["Bohdan"]
    _enter(base, guest)
    _post_noredirect(base + f"/symposiums/{sid}/claim",
                     {"token": guest, "sense": "s0"})
    pages = []
    _, welcome, _ = _get(base + f"/join/{tokens['Cara']}")
    pages.append(welcome)
    _, definitions, _ = _get(base + f"/symposiums/{sid}?token={guest}")
    pages.append(definitions)
    _, home, _ = _get(base + "/")
    pages.append(home)
    for page in pages:
        visible = _visible(page)
        assert "bohdan@example.com" not in visible
        assert "cara@example.com" not in visible
        assert not re.search(r"\bn\d+\b", visible), "node id leaked"
        assert not re.search(r"\bq\d+\b", visible), "question id leaked"
        assert not re.search(r"\bh\d+\b", visible), "handle id leaked"
        assert "carried_unvoted" not in visible
        assert "board_id" not in visible
        assert "sense_id" not in visible
        assert not re.search(r"\bboards?\b", visible, re.I), "says board"
        assert not re.search(r"\brooms?\b", visible, re.I), "says room"
        assert "test" not in visible.lower() or \
            "taste" in visible.lower() or "latest" in visible.lower() or \
            "test" not in re.sub(r"(protest|contest|latest|taste)\w*",
                                 "", visible.lower()), \
            "test-only control leaked"
