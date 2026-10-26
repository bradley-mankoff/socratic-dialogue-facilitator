"""Symposium start, players page, welcome and first definition.

Beads sdf-mgt.11 then sdf-zj6.2: the host starts from the Symposia landing
page on the start screen (own name and email, Settings: the Symposium's
name, the word, Anonymous Mode), adds players with "Add a player"
on the players page, and each guest arrives through a welcome page before
the pick-or-write of the first definition.

Seam: HTTP over loopback on a free port (``web.forum`` stdlib server over a
real ``BoardService`` with a stubbed dictionary chain). Every behaviour is
driven the way a person drives it: start form -> players page with personal
links -> welcome page -> definitions page -> pick-or-write.

Stdlib only: ``urllib`` client, ``http.server`` under test, no live network
(the autouse ``no_live_network`` guard stands behind every test here).
"""

from __future__ import annotations

import re

from tests.forum_http import (
    add_player,
    claim,
    enter,
    has_go_in_button,
    http_get,
    http_get_noredirect,
    invite_tokens,
    live_forum,
    parse_start,
    serve,
    start_and_tokens,
    start_on_players,
    start_symposium,
    visible,
)
from tests.sdf5_stubs import DATE, S0, make_service


# -- the host starts a Symposium on one screen -----------------------------

def test_start_form_names_a_symposium_not_a_board_or_room(live_forum):
    base, _service = live_forum
    _, start, _ = http_get(base + "/start")
    assert 'name="host_name"' in start
    assert 'name="host_email"' in start
    assert 'name="symposium_name"' in start
    assert 'name="word"' in start and 'name="anonymous"' in start
    assert "Settings" in start
    assert 'name="guests"' not in start, \
        "the guest box is gone: guests name themselves on arrival"
    shown = visible(start)
    assert not re.search(r"\bboards?\b", shown, re.I), "says board"
    assert not re.search(r"\brooms?\b", shown, re.I), "says room"


def test_host_start_opens_for_talk_at_once_with_no_begin_button(live_forum):
    base, _service = live_forum
    players_page, tokens, sid = start_and_tokens(base)
    assert "Share" in players_page
    for name, token in tokens.items():
        _, welcome, _ = http_get(base + f"/join/{token}")
        assert "Begin" not in welcome
    _, definitions, _ = http_get(
        base + f"/symposiums/{sid}?token={tokens['Ada']}")
    assert "Justice" in definitions
    assert "Begin" not in definitions


def test_every_start_makes_a_new_symposium(live_forum):
    base, service = live_forum
    _players_page_a, _tokens_a, sid_a = start_and_tokens(base)
    before = len(service.registry.boards)
    _url_b, _host_b, sid_b = start_on_players(base)
    assert sid_b != sid_a
    assert len(service.registry.boards) == before + 1


# -- the players page and the welcome page ----------------------------------

def test_first_visit_shows_welcome_with_word_people_how_it_works(live_forum):
    base, _service = live_forum
    _players_page, tokens, _sid = start_and_tokens(base)
    _, welcome, _ = http_get(base + f"/join/{tokens['Cara']}")
    assert "Justice" in welcome
    assert "Ada" in welcome, "the named host is company on the welcome"
    assert has_go_in_button(welcome)
    # the welcome page names names, never emails
    assert "ada@example.com" not in welcome


# -- definitions with small linked source notes ------------------------------

def test_definitions_end_with_small_linked_source_notes(live_forum):
    base, _service = live_forum
    _invites, tokens, sid = start_and_tokens(base)
    enter(base, tokens["Ada"])
    _, page, _ = http_get(base + f"/symposiums/{sid}?token={tokens['Ada']}")
    assert S0 in page
    assert re.search(
        r'<small><a href="https://[^"]+">\(Wiktionary\)</a></small>', page), \
        page[page.find(S0):page.find(S0) + 400]


def test_no_license_or_access_date_on_definitions(live_forum):
    base, _service = live_forum
    _invites, tokens, sid = start_and_tokens(base)
    enter(base, tokens["Ada"])
    _, page, _ = http_get(base + f"/symposiums/{sid}?token={tokens['Ada']}")
    shown = visible(page)
    assert "CC BY-SA" not in shown
    assert "unverified-upstream" not in shown
    assert "License" not in shown and "license" not in shown
    assert DATE not in shown
    assert "Accessed" not in shown and "accessed" not in shown


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

def test_first_claim_picks_a_dictionary_definition(live_forum):
    base, service = live_forum
    _players_page, tokens, sid = start_and_tokens(base)
    enter(base, tokens["Cara"])
    status, _page, headers = claim(base, sid, tokens["Ada"], sense="s0")
    assert status == 303
    _, page, _ = http_get(base + f"/symposiums/{sid}?token={tokens['Ada']}")
    assert S0 in page
    assert "dictionary" in page.lower()
    assert "Ada" in page
    assert "Claim the definition" not in page
    assert "Pick one" not in page
    assert "Or write your own" not in page
    state = service.state(service.registry.by_id(sid).board_id) \
        if service.registry.by_id(sid) is not None else None
    assert state is None or state.active_node_id is not None


def test_first_claim_writes_ones_own_in_a_fresh_symposium(live_forum):
    base, _service = live_forum
    players_page_url, host_token, sid = start_on_players(base, word="Courage")
    add_player(base, sid, host_token)
    _, players_page, _ = http_get(players_page_url)
    (guest,) = invite_tokens(players_page).values()
    enter(base, guest)
    mine = "Courage is facing fear for what matters."
    status, _page, _headers = claim(base, sid, guest, original=mine)
    assert status == 303
    _, page, _ = http_get(base + f"/symposiums/{sid}?token={guest}")
    assert mine in page
    assert "Claim the definition" not in page


def test_second_claim_refused_with_plain_message_journal_untouched(live_forum):
    base, service = live_forum
    _players_page, tokens, sid = start_and_tokens(base)
    enter(base, tokens["Cara"])
    claim(base, sid, tokens["Ada"], sense="s0")
    board_id = service.registry.by_id(sid).board_id
    before = service.machine(board_id).state.seq
    nodes_before = len(service.machine(board_id).state.nodes)
    status, page, _ = claim(
        base, sid, tokens["Cara"], original="Justice is order.")
    assert status == 200
    assert "already" in page.lower() and "active" in page.lower()
    assert "Error" not in page
    after = service.machine(board_id)
    assert after.state.seq == before
    assert len(after.state.nodes) == nodes_before
    status, page, _ = claim(base, sid, tokens["Cara"], sense="s1")
    assert status == 200
    assert "already" in page.lower() and "active" in page.lower()
    assert len(service.machine(board_id).state.nodes) == nodes_before


# -- the start page asks for people and a word, nothing else ---------------------

def test_start_page_has_no_facilitator_role_or_first_questioner(live_forum):
    base, _service = live_forum
    _, start, _ = http_get(base + "/start")
    assert 'name="mode"' not in start
    assert 'name="socrates"' not in start
    shown = visible(start)
    assert "Facilitator role" not in shown
    assert "first questioner" not in shown.lower()
    assert "keeps score" not in shown.lower()
    assert "takes part" not in shown.lower()


def test_symposium_starts_without_facilitator_fields(live_forum):
    base, service = live_forum
    players_page_url, host_token, sid = start_on_players(base)
    state = service.state(sid)
    assert state.active_node_id is None, "a fresh Symposium has no claim"
    _, page, _ = http_get(base + f"/symposiums/{sid}?token={host_token}")
    assert "Justice" in page
    assert "keeps score" not in page.lower()
    assert "takes part" not in page.lower()


def test_legacy_facilitator_fields_are_ignored(live_forum):
    base, service = live_forum
    players_page_url, host_token, sid = start_on_players(
        base, mode="facilitates", socrates="bohdan@example.com")
    _, players_page, _ = http_get(players_page_url)
    assert "Add a player" in players_page
    _, page, _ = http_get(base + f"/symposiums/{sid}?token={host_token}")
    assert "only keeps score" not in page.lower()
    assert "takes part" not in page.lower()


# -- host-only links ----------------------------------------------------------

def test_players_page_belongs_to_the_host_alone(live_forum):
    base, _service = live_forum
    _players_page, tokens, sid = start_and_tokens(base)
    enter(base, tokens["Bohdan"])
    status, _page, headers = http_get_noredirect(
        base + f"/symposiums/{sid}/players?token={tokens['Bohdan']}")
    assert status == 303
    location = headers.get("Location", "")
    assert f"/symposiums/{sid}" in location
    assert "token=" in location


def test_after_close_the_same_host_starts_a_numbered_next_one(live_forum):
    base, service = live_forum
    _players_page, tokens, sid = start_and_tokens(base)
    machine = service.machine(sid)
    handles = list(machine.state.handles)
    assert len(handles) >= 2, "the host and one invited handle"
    close_q = machine.open_governance_q("close", opened_by=handles[0])
    for handle in handles[:2]:
        machine.cast(close_q, handle, "explicit", "for")
    service.force_settle(sid, close_q)
    assert service.state(sid).status == "closed"
    players_page_url, _host, _sid = start_on_players(base)
    _, players_page, _ = http_get(players_page_url)
    assert "Friday Philosophers" in players_page, \
        "the next Symposium opens on its players page under its own name"


# -- empty dictionaries still leave a working page --------------------------------

def test_word_with_no_dictionary_entry_can_still_be_defined_by_hand(tmp_path):
    from tests.sdf5_stubs import empty_chain
    service = make_service(tmp_path / "store", chain=empty_chain())
    with serve(service) as base:
        status, _page, headers = start_symposium(base, word="Sophrosyne")
        assert status == 303
        _players_url, host_token, sid = parse_start(base, headers)
        _, page, _ = http_get(base + f"/symposiums/{sid}?token={host_token}")
        assert "No dictionary definitions were found" in page
        status, refused, _ = claim(base, sid, host_token, sense="s0")
        assert status == 200
        assert "write your own" in refused.lower()
        mine = "Sophrosyne is mastery of oneself."
        status, _page, _ = claim(base, sid, host_token, original=mine)
        assert status == 303
        _, page, _ = http_get(base + f"/symposiums/{sid}?token={host_token}")
        assert mine in page


# -- what no page may show ----------------------------------------------------

def test_no_page_shows_emails_machine_ids_boards_rooms_or_test_controls(
        live_forum):
    base, _service = live_forum
    players_page, tokens, sid = start_and_tokens(base)
    guest = tokens["Bohdan"]
    enter(base, guest)
    claim(base, sid, guest, sense="s0")
    pages = []
    _, welcome, _ = http_get(base + f"/join/{tokens['Cara']}")
    pages.append(welcome)
    _, definitions, _ = http_get(base + f"/symposiums/{sid}?token={guest}")
    pages.append(definitions)
    _, home, _ = http_get(base + "/")
    pages.append(home)
    # the host's players page joins the checked pages; invitation tokens
    # are random strings, not machine ids, so they are masked first.
    _, hosted, _ = http_get(base + f"/symposiums/{sid}/players"
                         f"?token={tokens['Ada']}")
    pages.append(hosted)
    for page in pages:
        shown = visible(page)
        assert "bohdan@example.com" not in shown
        assert "cara@example.com" not in shown
        masked = re.sub(r"/join/[A-Za-z0-9_-]+", "/join/TOKEN", shown)
        assert not re.search(r"\bn\d+\b", masked), "node id leaked"
        assert not re.search(r"\bq\d+\b", masked), "question id leaked"
        assert not re.search(r"\bh\d+\b", masked), "handle id leaked"
        assert "carried_unvoted" not in masked
        assert "board_id" not in masked
        assert "sense_id" not in masked
        assert not re.search(r"\bboards?\b", masked, re.I), "says board"
        assert not re.search(r"\brooms?\b", masked, re.I), "says room"
        assert "test" not in masked.lower() or \
            "taste" in masked.lower() or "latest" in masked.lower() or \
            "test" not in re.sub(r"(protest|contest|latest|taste)\w*",
                                 "", masked.lower()), \
            "test-only control leaked"
    assert "ada@example.com" in visible(hosted), \
        "only the host's own players page shows the host's email"
