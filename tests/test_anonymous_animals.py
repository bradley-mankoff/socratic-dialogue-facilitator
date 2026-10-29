"""Anonymous Mode: email-only join, random animals, one rendering, Who Is Here (Bead sdf-zj6.17).

Seam: HTTP over loopback on a free port (``web.forum`` stdlib server over a
real ``BoardService`` with a stubbed dictionary chain), the same seam the
join and phone-start tests drive.
"""

from __future__ import annotations

from tests.forum_http import (
    add_player,
    claim,
    enter,
    has_go_in_button,
    http_get,
    http_post_noredirect,
    invite_tokens,
    join,
    live_forum,
    participant,
    players_url,
    start_and_tokens,
    visible,
)
from web.forum import ANIMAL_ICONS, ANIMAL_NAMES, PLAYER_COLORS


def test_anonymous_join_asks_only_for_email(live_forum):
    base, _service = live_forum
    _players_page, tokens, _sid = start_and_tokens(base, guests=1, anonymous="on")
    status, form, _ = http_get(base + f"/join/{tokens['Bohdan']}")
    assert status == 200
    assert 'name="email"' in form, \
        "with Anonymous Mode on, a first visit asks for an email"
    assert 'name="name"' not in form, \
        "with Anonymous Mode on, a first visit asks for no name"
    assert 'name="color"' not in form, \
        "with Anonymous Mode on, a first visit offers no color"


def test_anonymous_join_deals_a_unique_animal_with_icon(live_forum):
    base, service = live_forum
    _players_page, tokens, sid = start_and_tokens(base, guests=2, anonymous="on")
    for name, address in (("Bohdan", "bohdan@example.com"),
                          ("Cara", "cara@example.com")):
        status, _page, headers = http_post_noredirect(
            base + f"/join/{tokens[name]}", {"email": address})
        assert status == 303, f"{name} joins with only an email"
        assert headers.get("Location", "").endswith(f"/join/{tokens[name]}"), \
            "joining walks to the instructions screen"
    first = participant(service, sid, tokens["Bohdan"])
    second = participant(service, sid, tokens["Cara"])
    assert first.get("animal") in ANIMAL_NAMES, first
    assert second.get("animal") in ANIMAL_NAMES, second
    assert first["animal"] != second["animal"], \
        "no two animals alike in one Symposium"
    assert first.get("name") is None and second.get("name") is None, \
        "with Anonymous Mode on there is no name"
    assert first.get("color") is None and second.get("color") is None, \
        "with Anonymous Mode on there is no color"
    assert first.get("email") == "bohdan@example.com", \
        "the email is kept as with Anonymous Mode off"
    _, instructions, _ = http_get(base + f"/join/{tokens['Bohdan']}")
    icon = ANIMAL_ICONS[first["animal"]]
    assert icon in instructions and first["animal"] in instructions, \
        "the animal is shown as its icon with its name beside it"
    assert "bohdan@example.com" not in instructions, \
        "the email is never shown"
    host = participant(service, sid, tokens["Ada"])
    assert host.get("animal") in ANIMAL_NAMES, \
        "the host gets a random animal the same way"
    _, players, _ = http_get(
        base + f"/symposiums/{sid}/players?token={tokens['Ada']}")
    assert ANIMAL_ICONS[host["animal"]] in players
    assert host["animal"] in visible(players), \
        "the host's players page shows the host's animal"


def test_no_name_on_any_page_including_after_a_claim(live_forum):
    base, service = live_forum
    _players_page, tokens, sid = start_and_tokens(base, guests=2, anonymous="on")
    host, first, second = tokens["Ada"], tokens["Bohdan"], tokens["Cara"]
    for token, address in ((first, "bohdan@example.com"),
                           (second, "cara@example.com")):
        status, _page, _headers = http_post_noredirect(
            base + f"/join/{token}", {"email": address})
        assert status == 303
    for token in (host, first, second):
        enter(base, token)
    animals = [participant(service, sid, t).get("animal") for t in (host, first, second)]
    assert len(set(animals)) == 3
    status, _page, _headers = claim(
        base, sid, host, original="Justice is order kept kindly.")
    assert status == 303
    # A guest invited after the claim still passes through the one
    # instructions screen: joining walks them there, listing who else
    # has joined through the animal rendering. (Fetching /join/{second}
    # here would only redirect to the Symposium page, since that guest
    # already went in.)
    add_player(base, sid, host)
    _, players_after, _ = http_get(players_url(base, sid, host))
    late = next(t for t in invite_tokens(players_after).values()
                if t not in tokens.values())
    status, _page, _headers = http_post_noredirect(
        base + f"/join/{late}", {"email": "dara@example.com"})
    assert status == 303
    pages = {}
    _, pages["players"], _ = http_get(players_url(base, sid, host))
    _, pages["instructions"], _ = http_get(base + f"/join/{late}")
    assert has_go_in_button(pages["instructions"]), \
        "a joined guest who has not gone in yet sees the instructions screen"
    for label, token in (("host symposium", host),
                         ("guest symposium", first)):
        _, body, _ = http_get(base + f"/symposiums/{sid}?token={token}")
        pages[label] = body
    for label, body in pages.items():
        shown = visible(body)
        assert "Ada" not in shown, label
        assert "Bohdan" not in shown, label
        assert "Cara" not in shown, label
        assert "bohdan@example.com" not in body, label
        assert "cara@example.com" not in body, label
        assert "ada@example.com" not in body or label == "players", label
    symposium = pages["guest symposium"]
    assert "Justice is order kept kindly." in visible(symposium)
    for animal in animals:
        assert animal in visible(symposium), \
            f"every page shows participants through the one animal rendering: {animal!r} missing"


def test_anonymous_refusal_keeps_nothing_and_rejoin_keeps_the_first_animal(live_forum):
    base, service = live_forum
    _players_page, tokens, sid = start_and_tokens(base, guests=1, anonymous="on")
    token = tokens["Bohdan"]
    status, refused, _ = http_post_noredirect(
        base + f"/join/{token}", {"email": "not-an-email"})
    assert status == 200, "a bad email re-renders the form"
    assert "name@example.com" in refused
    assert "not-an-email" not in refused, \
        "a refusal never echoes the email back"
    status, _page, _headers = http_post_noredirect(
        base + f"/join/{token}", {"email": "bohdan@example.com"})
    assert status == 303
    first = participant(service, sid, token).get("animal")
    status, _page, _headers = http_post_noredirect(
        base + f"/join/{token}", {"email": "someone-else@example.com"})
    assert status == 303, "joining again walks back to the instructions"
    again = participant(service, sid, token)
    assert again.get("animal") == first, \
        "joining twice never deals a second animal"
    assert again.get("email") == "bohdan@example.com", \
        "joining twice keeps the first email"


def test_who_is_here_lists_everyone_and_whether_each_joined(live_forum):
    base, service = live_forum
    _players_page, tokens, sid = start_and_tokens(base, guests=2, anonymous="on")
    host, first, second = tokens["Ada"], tokens["Bohdan"], tokens["Cara"]
    status, _page, _headers = http_post_noredirect(
        base + f"/join/{first}", {"email": "bohdan@example.com"})
    assert status == 303
    for token in (host, first):
        enter(base, token)
    _, symposium, _ = http_get(base + f"/symposiums/{sid}?token={host}")
    assert "Who Is Here" in symposium, \
        "the Symposium page gets a small Who Is Here panel"
    panel = symposium.split("Who Is Here")[1]
    shown = visible(symposium)
    host_animal = participant(service, sid, host).get("animal")
    first_animal = participant(service, sid, first).get("animal")
    assert host_animal in shown and first_animal in shown, \
        "the panel lists everyone through the animal rendering"
    assert ANIMAL_ICONS[host_animal] in panel
    assert panel.count("Joined") >= 2, \
        "the panel says whether each participant has joined yet"
    assert "Invited" in panel, \
        "the participant who has not joined yet reads as Invited"
    assert "bohdan@example.com" not in symposium
    assert "cara@example.com" not in symposium
    assert "ada@example.com" not in symposium, \
        "the panel never shows an email"


def test_who_is_here_unjoined_row_goes_through_the_badge(live_forum):
    base, _service = live_forum
    _players_page, tokens, sid = start_and_tokens(base, guests=2, anonymous="on")
    host, first = tokens["Ada"], tokens["Bohdan"]
    status, _page, _headers = http_post_noredirect(
        base + f"/join/{first}", {"email": "bohdan@example.com"})
    assert status == 303
    enter(base, host)
    _, symposium, _ = http_get(base + f"/symposiums/{sid}?token={host}")
    panel = symposium.split("Who Is Here")[1]
    assert "Invited — Invited" not in panel, \
        "an unjoined row never repeats the status as its own label"
    assert "Guest — Invited" in visible(symposium), \
        "an unjoined row goes through the one rendering, then its status"


def test_who_is_here_with_anonymous_mode_off(live_forum):
    base, _service = live_forum
    _players_page, tokens, sid = start_and_tokens(base, guests=2)
    host, first = tokens["Ada"], tokens["Bohdan"]
    status, _page, _headers = join(base, host, color=PLAYER_COLORS[0][1])
    assert status == 303
    status, _page, _headers = join(
        base, first, name="Bohdan", email="bohdan@example.com",
        color=PLAYER_COLORS[1][1])
    assert status == 303
    enter(base, host)
    _, symposium, _ = http_get(base + f"/symposiums/{sid}?token={host}")
    assert "Who Is Here" in symposium
    panel = symposium.split("Who Is Here")[1]
    assert "Bohdan — Joined" in visible(symposium), \
        "the panel lists a joined guest through the name rendering"
    assert "Guest — Invited" in visible(symposium), \
        "the guest who has not joined yet reads as Invited"
    assert "Invited — Invited" not in panel
    assert "bohdan@example.com" not in symposium
    assert "ada@example.com" not in symposium, \
        "the panel never shows an email"
