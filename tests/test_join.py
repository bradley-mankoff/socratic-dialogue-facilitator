"""Join from a personal link: name, email and color, then one instructions screen (Bead sdf-zj6.3).

Seam: HTTP over loopback on a free port (``web.forum`` stdlib server over a
real ``BoardService`` with a stubbed dictionary chain). Every behaviour is
driven the way a person drives it on their phone: opening a personal link
for the first time asks for a name, an email and a player color, then
shows the same instructions screen the host sees, with a Go In button.

Stdlib only: ``urllib`` client, ``http.server`` under test, no live network
(the autouse ``no_live_network`` guard stands behind every test here).
"""

from __future__ import annotations

from tests.forum_http import (
    enter,
    has_go_in_button,
    http_get,
    http_get_noredirect,
    http_post_noredirect,
    join,
    live_forum,
    start_and_tokens,
    visible,
)


def test_first_visit_asks_for_name_email_and_color(live_forum):
    base, _service = live_forum
    _players_page, tokens, _sid = start_and_tokens(base, guests=1)
    status, form, _ = http_get(base + f"/join/{tokens['Bohdan']}")
    assert status == 200
    assert 'name="name"' in form, \
        "a guest's first visit asks for their name"
    assert 'name="email"' in form, \
        "a guest's first visit asks for their email"
    colors = form.count('name="color"')
    assert colors >= 12, \
        f"about twelve player colors to pick from, found {colors}"
    assert not has_go_in_button(form), \
        "the join form is not the instructions screen: no Go In yet"


def test_after_joining_the_same_instructions_screen_appears(live_forum):
    from web.forum import PLAYER_COLORS
    base, _service = live_forum
    _players_page, tokens, _sid = start_and_tokens(base, guests=1)
    token = tokens["Bohdan"]
    status, _page, headers = join(
        base, token, name="Bohdan", email="bohdan@example.com",
        color=PLAYER_COLORS[0][1])
    assert status == 303, "joining walks to the instructions screen"
    location = headers.get("Location", "")
    assert location.endswith(f"/join/{token}"), location
    _, instructions, _ = http_get(base + location)
    assert "<h1>Friday Philosophers</h1>" in instructions, \
        "the instructions screen is headed by the Symposium's name"
    assert "Bohdan" in instructions, "the guest reads their own name"
    assert "Ada" in instructions, "who else has joined, by name"
    assert has_go_in_button(instructions)
    shown = visible(instructions)
    assert "Welcome," not in shown, "the screen names through its list"
    lowered = instructions.lower()
    assert "everyone takes turns putting forward a definition " \
        "and defending it." in lowered
    assert "everyone takes turns offering a counterexample " \
        "against it." in lowered
    assert "the group votes on each counterexample, and on when to set " \
        "a definition aside and move on." in lowered
    assert "bohdan@example.com" not in instructions, \
        "nobody's email reaches any page"


def test_a_taken_name_is_refused_with_a_plain_message(live_forum):
    from web.forum import PLAYER_COLORS
    base, _service = live_forum
    _players_page, tokens, _sid = start_and_tokens(base, guests=2)
    first, second = tokens["Bohdan"], tokens["Cara"]
    status, _page, _headers = join(
        base, first, name="Bohdan", email="bohdan@example.com",
        color=PLAYER_COLORS[0][1])
    assert status == 303
    status, refused, _ = join(
        base, second, name="bohdan ", email="cara@example.com",
        color=PLAYER_COLORS[1][1])
    assert status == 200, "a taken name re-renders the form, not the forum"
    assert "That name is taken." in refused
    assert "Please choose another." in refused
    assert "cara@example.com" not in refused, \
        "a refusal never echoes the email back"
    status, host_taken, _ = join(
        base, second, name="ada", email="cara@example.com",
        color=PLAYER_COLORS[1][1])
    assert status == 200
    assert "That name is taken." in host_taken, \
        "the host's name is taken too"


def test_taken_colors_are_greyed_out_and_refused(live_forum):
    import re
    from web.forum import PLAYER_COLORS
    base, _service = live_forum
    _players_page, tokens, _sid = start_and_tokens(base, guests=2)
    first, second = tokens["Bohdan"], tokens["Cara"]
    taken, free = PLAYER_COLORS[0][1], PLAYER_COLORS[2][1]
    status, _page, _headers = join(
        base, first, name="Bohdan", email="bohdan@example.com",
        color=taken)
    assert status == 303
    _, form, _ = http_get(base + f"/join/{second}")
    tag = re.search(
        r'<input[^>]*name="color"[^>]*value="' + re.escape(taken) + r'"[^>]*>',
        form)
    assert tag is not None, "the taken color is still listed"
    assert "disabled" in tag.group(0), "a taken color is greyed out"
    status, refused, _ = join(
        base, second, name="Cara", email="cara@example.com", color=taken)
    assert status == 200, "posting a taken color re-renders the form"
    assert "That color is already taken." in refused
    assert "Please pick another." in refused
    status, _page, _headers = join(
        base, second, name="Cara", email="cara@example.com", color=free)
    assert status == 303, "a free color joins"


def test_the_players_page_names_a_player_once_they_join(live_forum):
    import re
    from web.forum import PLAYER_COLORS
    base, _service = live_forum
    before, tokens, sid = start_and_tokens(base, guests=1)
    players_page_url = base + f"/symposiums/{sid}/players?token={tokens['Ada']}"
    assert before.count('class="who">Invited') == 1
    guest = tokens["Bohdan"]
    tint = PLAYER_COLORS[3][1]
    status, _page, _headers = join(
        base, guest, name="Bohdan", email="bohdan@example.com", color=tint)
    assert status == 303
    _, after, _ = http_get(players_page_url)
    assert 'class="who">Invited' not in after, \
        "the row reads the player's name instead of Invited"
    row = re.search(
        r'<span class="who">.*?</li>', after, re.S).group(0)
    assert "Bohdan" in row
    assert ">B</span> Bohdan" in row and tint in row, \
        "their icon is the first letter of their name in their color"
    assert "bohdan@example.com" not in after


def test_a_second_visit_goes_straight_in(live_forum):
    from web.forum import PLAYER_COLORS
    base, _service = live_forum
    _players_page, tokens, sid = start_and_tokens(base, guests=1)
    guest = tokens["Bohdan"]
    status, _page, _headers = join(
        base, guest, name="Bohdan", email="bohdan@example.com",
        color=PLAYER_COLORS[0][1])
    assert status == 303
    location = enter(base, guest)
    assert f"/symposiums/{sid}" in location
    page_url = location if location.startswith("http") else base + location
    _, inside, _ = http_get(page_url)
    assert "Friday Philosophers" in inside
    status, _body, headers = http_get_noredirect(base + f"/join/{guest}")
    assert status == 303, "a second visit goes straight in"
    assert f"/symposiums/{sid}" in headers.get("Location", "")
    _, straight_in, _ = http_get(base + f"/join/{guest}")
    assert "Friday Philosophers" in straight_in
    assert "Go In" not in straight_in, "no instructions screen twice"


def test_the_host_picks_a_color_and_sees_the_same_instructions(live_forum):
    from web.forum import PLAYER_COLORS
    base, _service = live_forum
    _players_page, tokens, sid = start_and_tokens(base, guests=1)
    host, guest = tokens["Ada"], tokens["Bohdan"]
    guest_color, host_color = PLAYER_COLORS[0][1], PLAYER_COLORS[1][1]
    status, _page, _headers = join(
        base, guest, name="Bohdan", email="bohdan@example.com",
        color=guest_color)
    assert status == 303
    symposium_url = base + f"/symposiums/{sid}?token={host}"
    status, _body, headers = http_get_noredirect(symposium_url)
    assert status == 303, \
        "the Symposium waits until the host picks their color"
    assert headers.get("Location", "").endswith(f"/join/{host}")
    _, form, _ = http_get(base + f"/join/{host}")
    assert 'name="color"' in form, \
        "the host picks their own color the same way"
    assert 'name="name"' not in form and 'name="email"' not in form, \
        "their name and email came from the start screen"
    assert "Joining as Ada" in visible(form)
    assert form.count('name="color"') >= 12
    status, refused, _ = join(base, host, color=guest_color)
    assert status == 200
    assert "That color is already taken." in refused
    status, _page, headers = join(base, host, color=host_color)
    assert status == 303
    _, instructions, _ = http_get(base + headers.get("Location", ""))
    assert "<h1>Friday Philosophers</h1>" in instructions, \
        "the host sees the same instructions screen"
    assert "Bohdan" in instructions, "who else has joined, by name"
    assert has_go_in_button(instructions)
    lowered = instructions.lower()
    assert "everyone takes turns putting forward a definition " \
        "and defending it." in lowered
    location = enter(base, host)
    assert f"/symposiums/{sid}" in location
    status, _body, headers = http_get_noredirect(base + f"/join/{host}")
    assert status == 303, "the host's second visit goes straight in"


def test_refusals_keep_the_name_and_color_but_never_the_email(live_forum):
    from web.forum import PLAYER_COLORS
    base, _service = live_forum
    _players_page, tokens, _sid = start_and_tokens(base, guests=1)
    guest = tokens["Bohdan"]
    tint = PLAYER_COLORS[4][1]
    status, refused, _ = join(
        base, guest, name="Bohdan", email="not-an-email", color=tint)
    assert status == 200
    assert "name@example.com" in refused
    assert "not-an-email" not in refused, \
        "a refusal never echoes the email back"
    assert 'value="Bohdan"' in refused, "the typed name is kept"
    assert f'value="{tint}" checked' in refused, "the picked color is kept"
    status, nameless, _ = join(
        base, guest, name="  ", email="bohdan@example.com", color=tint)
    assert status == 200
    assert "Please type your name" in nameless
    status, colorless, _ = join(
        base, guest, name="Bohdan", email="bohdan@example.com", color="")
    assert status == 200
    assert "Please pick a color." in colorless
    status, _page, _headers = join(
        base, guest, name="Bohdan", email="bohdan@example.com", color=tint)
    assert status == 303, "the same details join once fixed"


def test_no_page_shows_any_participants_email_to_anyone_else(live_forum):
    from web.forum import PLAYER_COLORS
    base, _service = live_forum
    players_page, tokens, sid = start_and_tokens(base, guests=2)
    host = tokens["Ada"]
    first, second = tokens["Bohdan"], tokens["Cara"]
    assert "ada@example.com" in players_page, \
        "the host's own players page shows their own email"
    status, _page, _headers = join(
        base, first, name="Bohdan", email="bohdan@example.com",
        color=PLAYER_COLORS[0][1])
    assert status == 303
    status, _page, _headers = join(
        base, host, color=PLAYER_COLORS[1][1])
    assert status == 303
    enter(base, first)
    enter(base, host)
    pages = []
    for label, url in (
            ("landing", base + "/"),
            ("start", base + "/start"),
            ("continue", base + "/continue"),
            ("guest form", base + f"/join/{second}"),
            ("guest instructions", base + f"/join/{first}"),
            ("host instructions", base + f"/join/{host}"),
            ("guest symposium",
             base + f"/symposiums/{sid}?token={first}"),
            ("host symposium",
             base + f"/symposiums/{sid}?token={host}")):
        status, body, _ = http_get(url)
        assert status == 200, label
        pages.append((label, body))
    for label, body in pages:
        assert "bohdan@example.com" not in body, label
        assert "cara@example.com" not in body, label
    for label, body in pages:
        if label == "host symposium" or label.startswith("host"):
            continue
        assert "ada@example.com" not in body, label
    _, hosted, _ = http_get(
        base + f"/symposiums/{sid}/players?token={host}")
    assert "ada@example.com" in hosted, \
        "only the host's own players page shows the host's email"
    assert "bohdan@example.com" not in hosted
    assert "cara@example.com" not in hosted


def test_joining_twice_keeps_the_first_name_email_and_color(live_forum):
    from web.forum import PLAYER_COLORS
    from tests.forum_http import participant
    base, service = live_forum
    _players_page, tokens, sid = start_and_tokens(base, guests=2)
    guest = tokens["Bohdan"]
    other_guest = tokens["Cara"]
    first, other = PLAYER_COLORS[0][1], PLAYER_COLORS[5][1]
    status, _page, _headers = join(
        base, guest, name="Bohdan", email="bohdan@example.com",
        color=first)
    assert status == 303
    status, _page, headers = join(
        base, guest, name="Zed", email="zed@example.com",
        color=other)
    assert status == 303, \
        "a second submit walks back to the instructions screen"
    assert headers.get("Location", "").endswith(f"/join/{guest}")
    _, instructions, _ = http_get(base + f"/join/{guest}")
    assert "Bohdan" in instructions
    assert "Zed" not in visible(instructions), \
        "joining is one-time: the first name stands"
    _, players, _ = http_get(
        base + f"/symposiums/{sid}/players?token={tokens['Ada']}")
    assert "Bohdan" in players and "Zed" not in players
    status, _page, _ = join(
        base, guest, name="Bohdan", email="bohdan@example.com",
        color=other)
    stored = participant(service, sid, guest)
    assert stored.get("name") == "Bohdan", \
        "the first name was never overwritten"
    assert stored.get("email") == "bohdan@example.com", \
        "the first email was never overwritten"
    assert stored.get("color") == first, \
        "the first color was never freed"
    import re
    _, other_form, _ = http_get(base + f"/join/{other_guest}")
    tag = re.search(
        r'<input[^>]*name="color"[^>]*value="' + re.escape(first) + r'"[^>]*>',
        other_form)
    assert tag is not None, "the first color is still listed"
    assert "disabled" in tag.group(0), \
        "the first color stays taken for another guest"


def test_the_symposium_waits_for_go_in_after_joining(live_forum):
    from web.forum import PLAYER_COLORS
    base, _service = live_forum
    _players_page, tokens, sid = start_and_tokens(base, guests=1)
    guest = tokens["Bohdan"]
    status, _page, _headers = join(
        base, guest, name="Bohdan", email="bohdan@example.com",
        color=PLAYER_COLORS[0][1])
    assert status == 303
    status, _body, headers = http_get_noredirect(
        base + f"/symposiums/{sid}?token={guest}")
    assert status == 303, \
        "the Symposium waits until Go In is pressed"
    assert headers.get("Location", "").endswith(f"/join/{guest}")
    _, instructions, _ = http_get(base + headers.get("Location", ""))
    assert ">Go In</button>" in instructions


def test_the_symposium_waits_for_go_in_after_the_host_picks_a_color(
        live_forum):
    from web.forum import PLAYER_COLORS
    base, _service = live_forum
    _players_page, tokens, sid = start_and_tokens(base, guests=1)
    host = tokens["Ada"]
    status, _page, _headers = join(
        base, host, color=PLAYER_COLORS[1][1])
    assert status == 303
    status, _body, headers = http_get_noredirect(
        base + f"/symposiums/{sid}?token={host}")
    assert status == 303, \
        "the Symposium waits until the host presses Go In"
    assert headers.get("Location", "").endswith(f"/join/{host}")
    _, instructions, _ = http_get(base + headers.get("Location", ""))
    assert ">Go In</button>" in instructions


def test_go_in_before_joining_leaves_the_row_invited(live_forum):
    base, _service = live_forum
    _players_page, tokens, sid = start_and_tokens(base, guests=1)
    guest = tokens["Bohdan"]
    status, _page, headers = http_post_noredirect(
        base + f"/join/{guest}/enter", {})
    assert status == 303, "pressing Go In answers with a redirect"
    assert headers.get("Location", "").endswith(f"/join/{guest}"), \
        "Go In before joining walks back to the join form, not in"
    _, after, _ = http_get(
        base + f"/symposiums/{sid}/players?token={tokens['Ada']}")
    assert 'class="who">Invited' in after, \
        "the row still reads Invited until the guest joins with details"
    assert "Bohdan" not in visible(after)
