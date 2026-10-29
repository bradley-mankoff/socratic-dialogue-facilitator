"""The host starts a Symposium in Symposia and shares each player's link (Bead sdf-zj6.2).

Seam: HTTP over loopback on a free port (``web.forum`` stdlib server over a
real ``BoardService`` with a stubbed dictionary chain). Every behaviour is
driven the way the host drives it on their phone: the landing page
(Symposia, Start or Continue) -> the start screen (own name and email,
Settings: the Symposium's name, the word, Anonymous Mode off by default)
-> Start opens the Symposium at once -> the players page, where each tap
on "Add a player" makes one row reading "Invited" with a note field and
a Share button carrying one message (the note, then the player's link).

Stdlib only: ``http.server`` under test, no live network
(the autouse ``no_live_network`` guard stands behind every test here).
"""

from __future__ import annotations

import html
import re
import shutil
import subprocess

import pytest

from server.symposium import SymposiumStore
from tests.forum_http import (
    add_player,
    claim,
    enter,
    has_go_in_button,
    http_get,
    http_get_noredirect,
    http_post_noredirect,
    invite_tokens,
    join,
    join_all,
    live_forum,
    participant,
    parse_start,
    players_url,
    run_at_once,
    save_note,
    share_button_messages,
    share_message,
    start_and_tokens,
    start_on_players,
    start_symposium,
    visible,
)
from web.forum import PLAYER_COLORS


def test_start_without_a_symposium_name_is_refused(live_forum):
    base, _service = live_forum
    status, body, _ = start_symposium(base, symposium_name="")
    assert status == 200, body[:500]
    assert "name your symposium" in body.lower(), body[:500]


def test_share_note_endpoint_reads_the_player_field_alone(live_forum):
    base, _service = live_forum
    _players_page, tokens, sid = start_and_tokens(base, guests=1)
    host_token, player_token = tokens["Ada"], tokens["Bohdan"]
    status, body, _ = http_post_noredirect(
        base + f"/symposiums/{sid}/players/note",
        {"token": host_token, "person": player_token,
         "note": "For Bohdan"},
        headers={"Accept": "text/plain"})
    assert status == 200, body[:500]
    assert "For Bohdan" not in body, \
        "the note endpoint reads the player field alone: " \
        "a person field saves nothing"
    _, players_page, _ = http_get(players_url(base, sid, host_token))
    found = share_button_messages(players_page)
    assert found[player_token] == f"{base}/join/{player_token}", \
        "the row still shares the link alone"


def test_share_note_endpoint_with_empty_note_sends_only_the_link(live_forum):
    base, _service = live_forum
    _players_page, tokens, sid = start_and_tokens(base, guests=1)
    status, body = share_message(
        base, sid, tokens["Ada"], tokens["Bohdan"], "   ")
    assert status == 200, body[:500]
    assert body == f"{base}/join/{tokens['Bohdan']}", body


def test_share_note_endpoint_trims_and_limits_the_note(live_forum):
    base, _service = live_forum
    _players_page, tokens, sid = start_and_tokens(base, guests=1)
    long_note = "  " + "x" * 250 + "  "
    status, body = share_message(
        base, sid, tokens["Ada"], tokens["Bohdan"], long_note)
    assert status == 200, body[:500]
    trimmed = "x" * 200
    assert body == f"{trimmed}\n{base}/join/{tokens['Bohdan']}", body
    assert len(trimmed) == 200


def test_share_message_is_the_note_then_the_personal_link(live_forum):
    # One test for the one Share message: the endpoint's answer for
    # each saved-note shape is the message, and each Share button
    # carries its own row's answer.
    base, _service = live_forum
    _players_page, tokens, sid = start_and_tokens(base, guests=3)
    host_token = tokens["Ada"]
    cases = [(tokens["Bohdan"], "   "),
             (tokens["Cara"], "For Cara, see you Friday"),
             (tokens["Dara"], "y" * 250)]
    expected = {}
    for player_token, note in cases:
        status, message = share_message(
            base, sid, host_token, player_token, note)
        assert status == 200, message[:500]
        expected[player_token] = message
    for player_token, message in expected.items():
        assert message.endswith("/join/" + player_token), message
        assert base in message, \
            "the personal link is built from the forum's address"
    assert "\n" not in expected[tokens["Bohdan"]], \
        "an empty note shares the link alone"
    assert expected[tokens["Cara"]].startswith(
        "For Cara, see you Friday\n"), \
        "the Share message is the row's note followed by the link"
    assert expected[tokens["Dara"]].startswith("y" * 200 + "\n"), \
        "a note over 200 characters shares trimmed to 200"
    assert "For Cara" not in expected[tokens["Dara"]] and \
        "y" * 200 not in expected[tokens["Cara"]] and \
        "For Cara" not in expected[tokens["Bohdan"]], \
        "one player's note never travels with another player's link"
    _, players_page, _ = http_get(players_url(base, sid, host_token))
    assert share_button_messages(players_page) == expected, players_page[:2000]
    assert players_page.count("For Cara, see you Friday") == 2, \
        "the note sits in its row's field and its row's button message"


def test_share_flow_reads_the_carried_message(live_forum):
    # One row contract over HTTP: the button carries the server-built
    # message, the row has a note field and nothing else. The script's
    # pending and ordering rules are checked by running the shipped
    # script, in test_background_note_saves_settle_in_order below.
    base, _service = live_forum
    players_page, _tokens, _sid = start_and_tokens(base, guests=1)
    assert 'data-message="' in players_page, \
        "each Share button carries its row's server-built message"
    assert 'placeholder="Note to send with the link"' in players_page
    assert 'data-player="' in players_page, \
        "the Share button knows which player the note is for"
    assert 'data-note-url="' in players_page, \
        "typed notes save to the note endpoint in the background"
    assert 'class="copy"' not in players_page and "Copy</button>" not in players_page, \
        "there is no Copy button: Share alone carries the link"
    assert "Private note" not in players_page, \
        "no private note: the note travels to the invitee"
    assert "Save Note" not in players_page, \
        "each row has a note field and a Share button, no second button"
    assert "navigator.share" in players_page, \
        "the Share button opens the phone's own share menu"
    assert "Copied" in players_page, \
        "where the browser has no share function the button copies"


_SHARE_DRIVER_JS = r"""
// Runs the players page's shipped script against a stub browser and
// checks the Share contract by execution: the tap shares the button's
// carried message with no request in between, typing disables Share
// as Saving... before the pause ends, and overlapping background
// saves settle in order, so a stale answer never re-enables Share
// and never replaces a newer message. Usage:
//   node share_driver.js <script.js> <link>
const fs = require("fs");
const scriptPath = process.argv[2];
const LINK = process.argv[3];
const failures = [];
function check(name, cond) {
  if (!cond) { failures.push(name); }
  console.log((cond ? "PASS " : "FAIL ") + name);
}

const origSetTimeout = setTimeout;
let timers = [];
global.setTimeout = (fn, ms) => {
  const id = timers.length + 1;
  timers.push({id, fn, dead: false});
  return id;
};
global.clearTimeout = (id) => {
  for (const t of timers) { if (t.id === id) { t.dead = true; } }
};
function runTimers() {
  const due = timers;
  timers = [];
  for (const t of due) { if (!t.dead) { t.fn(); } }
}

let fetches = [];
global.fetch = (url, opts) => new Promise((resolve) => {
  fetches.push({url, opts, resolve});
});
function okResponse(text) {
  return {
    ok: true,
    headers: {get: () => "text/plain; charset=utf-8"},
    text: () => Promise.resolve(text),
  };
}
function badResponse() {
  return {
    ok: false,
    headers: {get: () => "text/plain; charset=utf-8"},
    text: () => Promise.resolve(""),
  };
}

let shared = [];
// Node ships a read-only global navigator, so a plain assignment
// would silently keep it: define the stub browser's instead.
Object.defineProperty(globalThis, "navigator", {
  value: {
    share: ({text}) => { shared.push(text); return Promise.resolve(); },
  },
  configurable: true,
  writable: true,
});

const listeners = {button: {}, field: {}};
const rowNote = {textContent: ""};
const field = {
  value: "",
  addEventListener: (ev, fn) => { listeners.field[ev] = fn; },
};
const row = {
  querySelector: (sel) => {
    if (sel === 'input[name="note"]') { return field; }
    if (sel === ".copied") { return rowNote; }
    return null;
  },
};
const button = {
  dataset: {
    token: "HOST",
    player: "PLAYER",
    noteUrl: "/symposiums/S/players/note",
    message: LINK,
  },
  disabled: false,
  textContent: "Share",
  addEventListener: (ev, fn) => { listeners.button[ev] = fn; },
  closest: () => row,
  parentElement: row,
};
global.document = {
  querySelectorAll: () => [button],
  createElement: () => ({value: "", select: () => {}}),
  body: {appendChild: () => {}, removeChild: () => {}},
  execCommand: () => true,
};

eval(fs.readFileSync(scriptPath, "utf8"));

async function settle() {
  await new Promise((r) => origSetTimeout(r, 20));
}

async function main() {
  const click = listeners.button.click;
  const onInput = listeners.field.input;
  check("the row wires one tap and one note field", !!click && !!onInput);

  click();
  await settle();
  check("the tap shares the carried message",
    shared.length === 1 && shared[0] === LINK);
  check("the tap makes no request before sharing", fetches.length === 0);

  field.value = "Hi";
  onInput();
  check("typing disables Share while saving",
    button.disabled === true && button.textContent === "Saving...");
  check("no request leaves before the pause ends", fetches.length === 0);
  runTimers();
  check("one save starts after the pause", fetches.length === 1);
  field.value = "Hi there";
  onInput();
  check("more typing keeps Share disabled",
    button.disabled === true && button.textContent === "Saving...");
  runTimers();
  check("more typing starts a second save", fetches.length === 2);
  const bodyOf = (i) => fetches[i].opts.body;
  check("each save carries its typed note",
    bodyOf(0).endsWith("note=" + encodeURIComponent("Hi")) &&
    bodyOf(1).endsWith("note=" + encodeURIComponent("Hi there")));

  fetches[0].resolve(okResponse("Hi\n" + LINK));
  await settle();
  check("a stale answer leaves Share disabled", button.disabled === true);
  check("a stale answer leaves Saving... up",
    button.textContent === "Saving...");
  check("a stale answer never replaces the message",
    button.dataset.message === LINK);

  fetches[1].resolve(okResponse("Hi there\n" + LINK));
  await settle();
  check("the latest answer enables Share",
    button.disabled === false && button.textContent === "Share");
  check("the latest answer replaces the message",
    button.dataset.message === "Hi there\n" + LINK);
  check("a saved note clears the row's notice", rowNote.textContent === "");
  click();
  await settle();
  check("the tap shares the saved note then the link",
    shared[1] === "Hi there\n" + LINK);

  field.value = "Hi there, Bohdan";
  onInput();
  runTimers();
  check("a further save starts", fetches.length === 3);
  field.value = "Hi there, Bohdan!";
  onInput();
  check("a newer edit disables Share at once, before its pause ends",
    button.disabled === true && button.textContent === "Saving...");
  check("no new save leaves while the newer pause runs",
    fetches.length === 3);
  fetches[2].resolve(okResponse("Hi there, Bohdan\n" + LINK));
  await settle();
  check("an old answer while a newer edit waits leaves Share disabled",
    button.disabled === true);
  check("an old answer while a newer edit waits keeps Saving... up",
    button.textContent === "Saving...");
  check("an old answer while a newer edit waits never replaces the message",
    button.dataset.message === "Hi there\n" + LINK);
  runTimers();
  check("the waited edit saves after its pause", fetches.length === 4);
  fetches[3].resolve(okResponse("Hi there, Bohdan!\n" + LINK));
  await settle();
  check("the waited edit's answer enables Share",
    button.disabled === false && button.textContent === "Share");
  check("the waited edit's answer replaces the message",
    button.dataset.message === "Hi there, Bohdan!\n" + LINK);

  field.value = "Hi there!";
  onInput();
  runTimers();
  field.value = "Hi there!!";
  onInput();
  runTimers();
  check("a fifth and sixth save start", fetches.length === 6);
  fetches[5].resolve(okResponse("Hi there!!\n" + LINK));
  await settle();
  check("the newer answer wins",
    button.dataset.message === "Hi there!!\n" + LINK &&
    button.disabled === false);
  fetches[4].resolve(okResponse("Hi there!\n" + LINK));
  await settle();
  check("an older answer arriving late is ignored",
    button.dataset.message === "Hi there!!\n" + LINK &&
    button.disabled === false);

  field.value = "unreachable";
  onInput();
  runTimers();
  check("a seventh save starts", fetches.length === 7);
  fetches[6].resolve(badResponse());
  await settle();
  check("a failed save re-enables Share",
    button.disabled === false && button.textContent === "Share");
  check("a failed save keeps the previous message",
    button.dataset.message === "Hi there!!\n" + LINK);
  check("a failed save says to try again",
    rowNote.textContent === "Could not save the note. Try again.");

  global.navigator.share = () =>
    Promise.reject(Object.assign(new Error("cancelled"), {name: "AbortError"}));
  click();
  await settle();
  check("a cancelled share clears the row and shows nothing",
    rowNote.textContent === "");
  check("a cancelled share shares nothing new", shared.length === 2);
  global.navigator.share = () => Promise.reject(new Error("not allowed"));
  click();
  await settle();
  check("a refused share copies the message instead",
    rowNote.textContent === "Copied");
  check("a refused share shares nothing new", shared.length === 2);
  global.navigator.share = ({text}) => {
    shared.push(text); return Promise.resolve(); };
  click();
  await settle();
  check("a fresh tap after Copied shares again",
    shared.length === 3 && shared[2] === "Hi there!!\n" + LINK);
  check("a fresh tap clears Copied first", rowNote.textContent === "");

  delete global.navigator.share;
  click();
  await settle();
  check("without a share menu the button copies",
    rowNote.textContent === "Copied");
  check("copying makes no request", fetches.length === 7);
  check("copying shares nothing new", shared.length === 3);

  if (failures.length) {
    console.log(failures.length + " FAILURES");
    process.exit(1);
  }
  console.log("ALL SHARE CHECKS PASS");
}

main().catch((err) => {
  console.log("FAIL driver error: " + (err && err.stack || err));
  process.exit(1);
});
"""


def test_background_note_saves_settle_in_order(live_forum, tmp_path):
    # The script's seam: run the shipped players page script in node
    # against a stub browser, so overlapping background saves are
    # driven for real instead of read as text.
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is needed to run the players page script")
    base, _service = live_forum
    players_page, tokens, _sid = start_and_tokens(base, guests=1)
    script = players_page.split("<script>")[1].split("</script>")[0]
    link = f"{base}/join/{tokens['Bohdan']}"
    driver = tmp_path / "share_driver.js"
    driver.write_text(_SHARE_DRIVER_JS)
    script_file = tmp_path / "players_script.js"
    script_file.write_text(script)
    proc = subprocess.run(
        [node, str(driver), str(script_file), link],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ALL SHARE CHECKS PASS" in proc.stdout, proc.stdout


# -- no page shows the host's email ----------------------------------------

def test_only_the_hosts_own_players_page_shows_the_hosts_email(live_forum):
    base, _service = live_forum
    _, home, _ = http_get(base + "/")
    assert "ada@example.com" not in home
    _, start, _ = http_get(base + "/start")
    assert "ada@example.com" not in start
    status, rerendered, _ = start_symposium(
        base, host_name="", anonymous="on")
    assert status == 200
    assert "ada@example.com" not in rerendered, \
        "even a re-rendered start form never echoes the email back"
    players_page, tokens, sid = start_and_tokens(base, guests=1)
    assert "ada@example.com" in players_page, \
        "the host's own players page shows their own email"
    token = tokens["Bohdan"]
    _, welcome, _ = http_get(base + f"/join/{token}")
    assert "ada@example.com" not in welcome
    enter(base, token)
    _, symposium, _ = http_get(base + f"/symposiums/{sid}?token={token}")
    assert "ada@example.com" not in symposium

# -- one phone-first stylesheet on every page ------------------------------

def test_every_page_has_the_phone_first_stylesheet(live_forum):
    base, _service = live_forum
    players_page, tokens, sid = start_and_tokens(base)
    names = [name for name in tokens if name != "Ada"]
    token = tokens[names[0]]
    _, welcome, _ = http_get(base + f"/join/{token}")
    _, symposium, _ = http_get(
        base + f"/symposiums/{sid}?token={tokens['Ada']}")
    _, home, _ = http_get(base + "/")
    for page in (home, players_page, welcome, symposium):
        assert 'name="viewport"' in page, \
            "readable on a phone without zooming"
        assert "/static/forum.css" in page, \
            "every page shares one phone-first stylesheet"
    status, css, headers = http_get_noredirect(base + "/static/forum.css")
    assert status == 200
    assert "text/css" in headers.get("Content-Type", "")
    assert "max-width" in css and "auto" in css, \
        "a narrow column that stays tidy on a wide screen"
    assert "max-width: 34rem" in css or "max-width:34rem" in css, \
        "a narrow phone column centred with margin auto"
    assert "margin" in css and "auto" in css
    assert "44px" in css, "thumb-sized tap targets"
    assert "min-height: 44px" in css or "min-height:44px" in css, \
        "buttons and inputs meet a thumb's tap target"
    assert "box-sizing" in css, "nothing pushes past the screen edge"
    assert "max-width: 100%" in css or "max-width:100%" in css, \
        "inputs and the page never exceed the 390px viewport"
    assert "width: 100%" in css or "width:100%" in css, \
        "fields fill the narrow column instead of overflowing it"
    for m in re.finditer(r"width:\s*(\d+)px", css):
        assert int(m.group(1)) <= 390, \
            f"no fixed width wider than a 390px phone: {m.group(0)}"

def test_stylesheet_never_scrolls_sideways_or_zooms_on_a_phone(live_forum):
    base, _service = live_forum
    status, css, _ = http_get_noredirect(base + "/static/forum.css")
    assert status == 200
    assert "overflow-x" in css, \
        "nothing may push past the screen edge on a 390px window"
    assert "0.9rem" not in css, \
        "no input under 16px: iOS zooms when a smaller field is focused"
    assert "font-size: 1rem" in css, \
        "link and note fields stay at phone-readable size"


# -- every link opens its welcome page; the host can add at any time -----

def test_opening_a_link_preview_never_signs_in_or_joins(live_forum):
    base, service = live_forum
    players_page, tokens, sid = start_and_tokens(base, guests=1)
    token = tokens["Bohdan"]
    assert token in players_page
    status, body, headers = http_get_noredirect(base + f"/join/{token}")
    assert status == 200
    assert headers.get("Set-Cookie") is None, \
        "previewing a guest's join form must not sign the host's" \
        " browser in as that guest"
    assert 'name="name"' in body and 'name="email"' in body, \
        "each link opens that person's join form"
    assert not has_go_in_button(body), \
        "the join form is not the instructions screen: no Go In yet"
    guest = participant(service, sid, token)
    assert guest.get("joined") is False, \
        "looking at the link never joins; only joining does"


def test_each_link_opens_its_join_form_and_goes_in(live_forum):
    base, _service = live_forum
    _players_page, tokens, sid = start_and_tokens(base, guests=2)
    guest_tokens = [token for name, token in tokens.items()
                    if name != "Ada"]
    assert len(set(guest_tokens)) == 2
    for token in guest_tokens:
        _, form, _ = http_get(base + f"/join/{token}")
        assert 'name="name"' in form and 'name="email"' in form, \
            "each link opens that person's join form"
    join_all(base, tokens)
    for token in guest_tokens:
        _, instructions, _ = http_get(base + f"/join/{token}")
        assert has_go_in_button(instructions), \
            "after joining, each link opens the instructions screen"
        location = enter(base, token)
        assert f"/symposiums/{sid}" in location
        page_url = (location if location.startswith("http")
                    else base + location)
        _, inside, _ = http_get(page_url)
        assert "Justice" in inside


def test_join_form_names_nobody_then_instructions_give_three_sentences(
        live_forum):
    base, _service = live_forum
    _players_page, tokens, _sid = start_and_tokens(base, guests=1)
    _, form, _ = http_get(base + f"/join/{tokens['Bohdan']}")
    assert "Ada" not in form, \
        "until the guest joins, the join form names nobody"
    assert not has_go_in_button(form)
    join_all(base, tokens)
    _, instructions, _ = http_get(base + f"/join/{tokens['Bohdan']}")
    assert "Ada" in instructions, "who else has joined, by name"
    lowered = instructions.lower()
    assert "everyone takes turns putting forward a definition " \
        "and defending it." in lowered
    assert "everyone takes turns offering a counterexample " \
        "against it." in lowered
    assert "the group votes on each counterexample, and on when to set " \
        "a definition aside and move on." in lowered


def test_host_adds_players_at_any_time_from_the_players_page(live_forum):
    base, _service = live_forum
    players_page_url, host_token, sid = start_on_players(base)
    add_player(base, sid, host_token)
    _, page, _ = http_get(players_page_url)
    (first,) = set(invite_tokens(page).values())
    join_all(base, {"Ada": host_token, "Bohdan": first})
    enter(base, first)
    enter(base, host_token)
    _, symposium, _ = http_get(base + f"/symposiums/{sid}?token={host_token}")
    assert "Justice" in symposium, "the Symposium is already going"
    add_player(base, sid, host_token)
    _, later, _ = http_get(players_page_url)
    assert len(set(invite_tokens(later).values())) == 2, \
        "the host comes back and adds people after the start"
    (second,) = set(invite_tokens(later).values()) - {first}
    _, form, _ = http_get(base + f"/join/{second}")
    assert "Friday Philosophers" in form, \
        "a late link opens the join form under the Symposium's name"


def test_host_opening_guest_link_sees_welcome_and_go_in_takes_that_place(
        live_forum):
    base, service = live_forum
    _players_page, tokens, sid = start_and_tokens(base, guests=1)
    host_token, token = tokens["Ada"], tokens["Bohdan"]
    host_cookie = {"Cookie": f"sdf_token={host_token}"}
    _, form, _ = http_get(base + f"/join/{token}",
                        headers=host_cookie)
    assert 'name="name"' in form, \
        "each link opens that person's join form, even for the host"
    status, _page, headers = join(
        base, token, name="Bohdan", email="bohdan@example.com",
        color=PLAYER_COLORS[0][1], headers=host_cookie)
    assert status == 303, \
        "joining signs that browser in as that person, with no password"
    assert f"/join/{token}" in headers.get("Location", "")
    assert token in (headers.get("Set-Cookie", "") or "")
    guest = participant(service, sid, token)
    assert guest.get("joined") is True
    assert guest.get("name") == "Bohdan"


# -- Add a player: one personal link with Share and a note -----------------


def test_each_tap_on_add_a_player_makes_one_new_personal_link(live_forum):
    base, _service = live_forum
    players_page_url, host_token, sid = start_on_players(base)
    _, empty, _ = http_get(players_page_url)
    assert 'class="who">Invited' not in empty
    add_player(base, sid, host_token)
    _, one, _ = http_get(players_page_url)
    assert len(set(invite_tokens(one).values())) == 1
    add_player(base, sid, host_token)
    _, two, _ = http_get(players_page_url)
    first, second = (set(invite_tokens(one).values()),
                     set(invite_tokens(two).values()))
    assert len(second) == 2 and first < second, \
        "each tap makes one new link and keeps the earlier ones"


def test_players_page_shows_no_raw_link_only_share(live_forum):
    base, _service = live_forum
    players_page, tokens, _sid = start_and_tokens(base, guests=1)
    token = tokens["Bohdan"]
    assert "readonly" not in players_page, \
        "no raw link sits in a text field on the players page"
    assert not re.search(r'value="https?://[^"]*/join/', players_page), \
        "no raw link sits in any field value on the players page"
    shown = re.sub(r'data-message="[^"]*"', "", players_page)
    assert "/join/" not in shown, \
        "no raw link shows outside the buttons' carried messages"
    assert token not in visible(players_page), \
        "the link itself never shows as reading text"


def test_personal_links_are_absolute_openable_and_copied(live_forum):
    base, _service = live_forum
    players_page, tokens, sid = start_and_tokens(base, guests=1)
    host_token, guest = tokens["Ada"], tokens["Bohdan"]
    status, message = share_message(
        base, sid, host_token, guest, "Hello")
    assert status == 200
    link = message.splitlines()[-1]
    assert link.startswith(base + "/join/"), link
    _, form, _ = http_get(link)
    assert 'name="name"' in form, "the link opens the guest's join form"
    status, _page, _headers = join(
        base, guest, name="Bohdan", email="bohdan@example.com",
        color=PLAYER_COLORS[0][1])
    assert status == 303
    location = enter(base, guest)
    assert f"/symposiums/{sid}" in location
    assert "execCommand" in players_page and "Copied" in players_page, \
        "the same button copies past navigator.clipboard (plain http has none)" \
        " and tells the host it worked"


def test_anonymous_on_hides_every_name_until_animals_arrive(live_forum):
    base, service = live_forum
    players_page, tokens, sid = start_and_tokens(base, guests=1, anonymous="on")
    players_page_url = players_url(base, sid, tokens["Ada"])
    host_token = tokens["Ada"]
    stored = SymposiumStore(service.root).get(sid)
    assert stored is not None and stored.get("anonymous") is True, \
        "Anonymous Mode is saved with the Symposium: everyone appears" \
        " as a random animal, with no name anywhere, not even the host's"
    _, players_page, _ = http_get(players_page_url)
    assert "Ada" not in visible(players_page), \
        "the host's own players page shows their animal, never their name"
    host = next(p for p in stored["participants"] if p["is_host"])
    assert host.get("animal"), "the host gets a random animal at Start"
    assert host["animal"] in visible(players_page)
    assert "ada@example.com" in players_page, \
        "the host's own players page still shows their own email"
    (token,) = set(invite_tokens(players_page).values())
    _, form, _ = http_get(base + f"/join/{token}")
    assert "Ada" not in form, \
        "a guest's join form never leaks the host's name" \
        " with Anonymous Mode on"
    enter(base, host_token)
    _, symposium, _ = http_get(base + f"/symposiums/{sid}?token={host_token}")
    assert "Justice" in symposium
    assert "Ada" not in symposium
    _, landing, _ = http_get(base + "/")
    assert "Ada" not in landing, \
        "the landing page never leaks a name with Anonymous Mode on"


def test_anonymous_on_claim_shows_no_name_on_the_symposium_page(live_forum):
    base, _service = live_forum
    _, host_token, sid = start_on_players(base, anonymous="on")
    enter(base, host_token)
    status, _page, _headers = claim(
        base, sid, host_token, original="Justice is order kept kindly.")
    assert status == 303, _page[:500]
    _, page, _ = http_get(base + f"/symposiums/{sid}?token={host_token}")
    shown = visible(page)
    assert "Justice is order kept kindly." in shown
    assert "Ada" not in shown, \
        "with Anonymous Mode on, claiming must not print the host's name"
    assert "Guest#" not in shown and "Guest-" not in shown, \
        "no internal handle suffix may ever reach a page"


def test_unjoined_guests_board_name_is_not_the_page_placeholder(live_forum):
    base, service = live_forum
    players_page_url, host_token, sid = start_on_players(base)
    add_player(base, sid, host_token)
    add_player(base, sid, host_token)
    _, players_page, _ = http_get(players_page_url)
    tokens = set(invite_tokens(players_page).values())
    assert len(tokens) == 2
    stored = SymposiumStore(service.root).get(sid)
    handles = service.machine(sid).state.handles
    for token in tokens:
        slot = next(p for p in stored["participants"]
                      if p["token"] == token)
        enrolled = handles[slot["handle_id"]].display
        assert enrolled != "Guest", \
            "the display name a handle is enrolled under stays separate" \
            " from the page placeholder, so no internal name can read as" \
            f" a guest's name: {enrolled!r}"


def test_named_guest_claim_shows_their_name_never_a_machine_suffix(live_forum):
    base, _service = live_forum
    players_page, tokens, sid = start_and_tokens(base, guests=2)
    names = [name for name in tokens if name != "Ada"]
    second = tokens[names[1]]
    join_all(base, tokens)
    enter(base, second)
    enter(base, tokens["Ada"])
    status, _page, _headers = claim(
        base, sid, second, original="Justice is fairness in action.")
    assert status == 303, _page[:500]
    _, symposium, _ = http_get(
        base + f"/symposiums/{sid}?token={tokens['Ada']}")
    shown = visible(symposium)
    assert "Justice is fairness in action." in shown
    assert "Guest#" not in symposium and "Guest-" not in symposium, \
        "no internal handle suffix may ever reach a page"
    assert "Guest slot" not in symposium, \
        "the display name the board enrolled stays off the page"
    assert "Cara" in shown, \
        "once a guest joins with their name, the page shows it"


def test_sign_in_cookie_is_persistent_so_the_host_keeps_a_way_back(live_forum):
    base, _service = live_forum
    status, _page, headers = start_symposium(base)
    assert status == 303
    cookie = headers.get("Set-Cookie", "")
    assert "Max-Age=" in cookie, \
        "the host's sign-in cookie must survive the browser closing"
    players_page_url, host_token, sid = parse_start(base, headers)
    add_player(base, sid, host_token)
    _, players_page, _ = http_get(players_page_url)
    (guest,) = set(invite_tokens(players_page).values())
    status, guest_page, guest_headers = http_post_noredirect(
        base + f"/join/{guest}/enter", {})
    assert status == 303, guest_page[:500]
    assert "Max-Age=" in guest_headers.get("Set-Cookie", ""), \
        "signing in as a guest persists too, so a closed browser keeps it"
    _, landing, _ = http_get(base + "/",
                              headers={"Cookie": cookie.split(";")[0]})
    assert "Symposia" in landing
    assert "Continue a Symposium" in landing, \
        "the landing page offers Continue a Symposium"
    assert host_token in cookie


def test_continue_names_the_hosts_way_back_when_signed_in(live_forum):
    base, _service = live_forum
    status, _page, headers = start_symposium(base)
    assert status == 303
    cookie = headers.get("Set-Cookie", "")
    jar = {"Cookie": cookie.split(";")[0]}
    _, coming, _ = http_get(base + "/continue", headers=jar)
    assert "Your Players Page" not in coming, \
        "Continue names the way back for the host's Symposium"
    way_back = re.search(
        r'<a[^>]*href="([^"]*/players[^"]*)"[^>]*>'
        r"Back to Friday Philosophers</a>", coming)
    assert way_back, coming[-800:]
    assert "button" in way_back.group(0), \
        "the way back wears the button look beside the Back button"
    assert "\u2190 Back" in coming, \
        "the plain Back button to the landing page stays"


def test_host_can_come_back_to_their_players_page(live_forum):
    base, _service = live_forum
    status, _page, headers = start_symposium(base)
    assert status == 303
    players_page_url, host_token, sid = parse_start(base, headers)
    cookie = headers.get("Set-Cookie", "")
    assert host_token in cookie, \
        "Start signs the host's browser in, so closing the tab loses nothing"
    jar = {"Cookie": cookie.split(";")[0]}
    _, landing, _ = http_get(base + "/", headers=jar)
    assert "Continue a Symposium" in landing
    status, body, _ = http_get_noredirect(
        base + f"/symposiums/{sid}/players", headers=jar)
    assert status == 200
    assert "Add a player" in body, \
        "the cookie alone reopens the players page, no URL needed"


def test_anonymous_on_host_claim_is_credited_to_the_host_handle(live_forum):
    base, service = live_forum
    players_page_url, host_token, sid = start_on_players(base, anonymous="on")
    add_player(base, sid, host_token)
    enter(base, host_token)
    status, _page, _headers = claim(
        base, sid, host_token, original="Justice is order kept kindly.")
    assert status == 303, _page[:500]
    host = participant(service, sid, host_token)
    assert service.machine(sid).defender() == host.get("handle_id")


@pytest.mark.parametrize("anonymous,guests", [(True, 1), (False, 2)])
def test_guest_claim_is_credited_to_their_own_handle(live_forum, anonymous, guests):
    base, service = live_forum
    kwargs = {"anonymous": "on"} if anonymous else {}
    _players_page, tokens, sid = start_and_tokens(base, guests=guests, **kwargs)
    guest = tokens["Bohdan"] if guests == 1 else tokens["Cara"]
    if anonymous:
        status, _page, _headers = join(
            base, guest, email="guest@example.com")
        assert status == 303, _page[:500]
    else:
        join_all(base, tokens)
    enter(base, guest)
    status, _page, _headers = claim(
        base, sid, guest, original="Justice is fairness in action.")
    assert status == 303, _page[:500]
    slot = participant(service, sid, guest)
    defender = service.machine(sid).defender()
    assert defender == slot.get("handle_id"), \
        "with Anonymous Mode on the renderer returns a placeholder, which must" \
        " never decide who the board records: the claim belongs to the" \
        f" guest's own stored handle, not {defender!r}"
    claimed_by = service.provenance(
        sid, service.state(sid).active_node_id or "").get("claimed_by") \
        if service.state(sid).active_node_id else None
    assert claimed_by == slot.get("handle_id")


def test_second_guest_can_join_on_same_phone_as_first(live_forum):
    base, service = live_forum
    _players_page, tokens, sid = start_and_tokens(base, guests=2)
    names = [name for name in tokens if name != "Ada"]
    first, second = tokens[names[0]], tokens[names[1]]
    status, _page, _headers = join(
        base, first, name="Bohdan", email="bohdan@example.com",
        color=PLAYER_COLORS[0][1])
    assert status == 303
    _, _, first_headers = http_post_noredirect(
        base + f"/join/{first}/enter", {})
    first_cookie = (first_headers.get("Set-Cookie", "") or "").split(";")[0]
    assert first in first_cookie
    jar = {"Cookie": first_cookie}
    status, preview, headers = http_get_noredirect(
        base + f"/join/{second}", headers=jar)
    assert status == 200
    assert headers.get("Set-Cookie") is None
    assert "someone else" not in preview.lower(), \
        "a second guest on the same phone still gets their own join form"
    assert 'name="name"' in preview
    assert "Bohdan" not in preview, \
        "the second form carries no name from the first guest"
    assert not has_go_in_button(preview), \
        "the join form is not the instructions screen: no Go In yet"
    status, body, headers = join(
        base, second, name="Cara", email="cara@example.com",
        color=PLAYER_COLORS[1][1], headers=jar)
    assert status == 303, body[:500]
    assert second in (headers.get("Set-Cookie", "") or "")
    slot = participant(service, sid, second)
    assert slot.get("joined") is True, \
        "my link is all I need: joining works even on a shared phone"
    assert slot.get("name") == "Cara"


def test_anonymous_on_welcome_says_group_is_there_without_naming(live_forum):
    base, _service = live_forum
    _players_page, tokens, _sid = start_and_tokens(base, guests=1, anonymous="on")
    token = tokens["Bohdan"]
    _, welcome, _ = http_get(base + f"/join/{token}")
    lowered = welcome.lower()
    assert "ada" not in lowered
    assert "just you for now" not in lowered, \
        "with Anonymous Mode on the welcome still says who else" \
        " is there, without names"
    assert "with " in lowered, \
        "the welcome says the group is there without naming it"


def test_players_page_lists_invited_not_guest_placeholders(live_forum):
    base, _service = live_forum
    players_page, _tokens, _sid = start_and_tokens(base, guests=2)
    assert players_page.count('class="who">Invited') == 2
    assert "Guest" not in visible(players_page), \
        "unjoined invitation slots never read as people named Guest"


def test_the_note_travels_in_the_share_message_only(live_forum):
    base, _service = live_forum
    players_page, tokens, sid = start_and_tokens(base, guests=1)
    players_page_url = players_url(base, sid, tokens["Ada"])
    host_token, token = tokens["Ada"], tokens["Bohdan"]
    save_note(base, sid, host_token, token, "for Sam")
    _, noted, _ = http_get(players_page_url)
    assert "for Sam" in noted, \
        "the note sits in its row's field and Share message"
    _, form, _ = http_get(base + f"/join/{token}")
    assert "for Sam" not in form, \
        "the guest's join form never shows the host's note"
    join_all(base, tokens)
    enter(base, token)
    _, symposium, _ = http_get(base + f"/symposiums/{sid}?token={token}")
    assert "for Sam" not in symposium, \
        "the Symposium page never shows the host's note"

# -- Add a player: many taps at once still make distinct links -------------

def test_many_taps_at_once_each_make_a_link_with_its_own_handle(live_forum):
    base, service = live_forum
    players_page_url, host_token, sid = start_on_players(base)
    before = set(service.machine(sid).state.handles)
    taps = 10
    results, errors = run_at_once(
        {f"tap-{i}": (lambda: add_player(base, sid, host_token))
         for i in range(taps)})
    assert not errors, errors
    assert len(results) == taps
    _, players_page, _ = http_get(players_page_url)
    tokens = set(invite_tokens(players_page).values())
    assert len(tokens) == taps, \
        "every tap at once still makes its own personal link"
    stored = SymposiumStore(service.root).get(sid)
    handle_ids = [p["handle_id"] for p in stored["participants"]
                    if not p.get("is_host")]
    assert len(handle_ids) == taps
    assert len(set(handle_ids)) == taps, \
        "every participant has a distinct board handle"
    after = set(service.machine(sid).state.handles)
    assert len(after) == len(before) + taps, \
        "the handles grew by that many"
    assert set(handle_ids) <= after


# -- Symposia landing: Start a Symposium or Continue a Symposium -----------

def test_landing_is_two_large_buttons_and_nothing_else(live_forum):
    base, _service = live_forum
    status, _page, headers = start_symposium(base)
    assert status == 303
    jar = {"Cookie": headers.get("Set-Cookie", "").split(";")[0]}
    _, signed_out, _ = http_get(base + "/")
    _, signed_in, _ = http_get(base + "/", headers=jar)
    for label, home in (("signed out", signed_out),
                         ("signed in", signed_in)):
        assert "<title>Symposia</title>" in home, \
            f"the landing page is titled Symposia {label}"
        assert home.count("Start a Symposium") == 1, \
            f"each choice appears once {label}: no heading plus link" \
            " saying the same words"
        assert home.count("Continue a Symposium") == 1, \
            f"each choice appears once {label}"
        assert "<h2" not in home, \
            f"the landing page has no subheadings {label}"
        assert "Your Players Page" not in home, \
            f"a signed-in browser sees no unexplained link {label}"
        for path, words in (("/start", "Start a Symposium"),
                             ("/continue", "Continue a Symposium")):
            link = re.search(
                r'<a[^>]*href="' + path + r'"[^>]*>'
                + re.escape(words) + r"</a>", home)
            assert link, f"the {words} choice is one link {label}"
            assert "button" in link.group(0), \
                f"the {words} choice wears the button look {label}"
        shown = visible(home)
        assert not re.search(r"\brooms?\b", shown, re.I), \
            f"the landing page never says room {label}"


def test_anonymous_is_stored_alone_with_a_single_name(live_forum):
    base, service = live_forum
    _, _host, sid = start_on_players(base, anonymous="on")
    stored = SymposiumStore(service.root).get(sid)
    assert stored.get("anonymous") is True
    assert "names_on" not in stored, "Anonymous Mode lives in one switch"
    assert "title" not in stored, "the Symposium name lives in one field"
    assert stored.get("name") == "Friday Philosophers"
    _, _host, sid = start_on_players(base)
    stored = SymposiumStore(service.root).get(sid)
    assert stored.get("anonymous") is False
    assert "names_on" not in stored
    assert "title" not in stored


def test_start_link_opens_the_start_screen_and_continue_says_coming(live_forum):
    base, _service = live_forum
    _, start, _ = http_get(base + "/start")
    assert "<title>Symposia</title>" in start
    assert 'name="host_name"' in start and 'name="host_email"' in start
    _, coming, _ = http_get(base + "/continue")
    assert "<title>Symposia</title>" in coming
    assert "coming" in visible(coming).lower()
    assert 'href="/"' in coming and "\u2190" in coming


def test_start_screen_has_settings_in_order_with_tooltips(live_forum):
    base, _service = live_forum
    _, start, _ = http_get(base + "/start")
    sym_pos = start.find('name="symposium_name"')
    word_pos = start.find('name="word"')
    anon_pos = start.find('name="anonymous"')
    assert sym_pos != -1 and word_pos != -1 and anon_pos != -1
    assert sym_pos < word_pos < anon_pos, \
        "Settings holds the Symposium's name, then the word, then Anonymous Mode"
    assert "Settings" in start
    assert 'name="anonymous" value="on" checked' not in start, \
        "Anonymous Mode is off by default"
    assert start.count('class=\"tip\"') >= 3, \
        "each setting has a tooltip"
    assert "Start a Symposium with its people" not in start, \
        "no instruction text above the form"


def test_setting_tooltips_work_on_a_phone(live_forum):
    base, _service = live_forum
    _, start, _ = http_get(base + "/start")
    # The tip control sits outside the label so tapping it never flips
    # the checkbox or focuses the text field; it is a button a thumb
    # can tap, with its text in the page for phones and the same text
    # as a hover title for computers.
    assert start.count('type="button" class="tip"') >= 3
    tips = re.findall(r'<button[^>]*class="tip"[^>]*>\?</button>', start)
    assert len(tips) >= 3
    texts = re.findall(r'class="tip-text"[^>]*>(.*?)</span>', start, re.S)
    assert len(texts) >= 3
    for label_match in re.finditer(r'<label[^>]*>.*?</label>', start, re.S):
        assert 'class="tip"' not in label_match.group(0), \
            "tapping ? must not activate the setting's control"
    assert "hidden" in start
    assert "button.tip" in start and "tip-text" in start, \
        "a little JavaScript toggles each tooltip on tap"


def test_setting_tooltips_read_the_same_on_and_off(live_forum):
    base, _service = live_forum
    _, off, _ = http_get(base + "/start")
    status, on, _ = start_symposium(
        base, host_name="", host_email="bad", anonymous="on")
    assert status == 200
    off_tips = re.findall(r'class="tip-text"[^>]*>(.*?)</span>', off, re.S)
    on_tips = re.findall(r'class="tip-text"[^>]*>(.*?)</span>', on, re.S)
    assert len(off_tips) >= 3 and off_tips == on_tips, \
        "each setting's tooltip explains it the same whatever its position"


def test_players_page_is_headed_by_the_symposium_name(live_forum):
    base, _service = live_forum
    players_page_url, _host, _sid = start_on_players(base)
    _, players_page, _ = http_get(players_page_url)
    assert "<title>Symposia</title>" in players_page
    assert "<h1>Friday Philosophers</h1>" in players_page, \
        "the players page is headed by the Symposium's name, with no suffix"
    assert "people" not in visible(players_page).split("Friday Philosophers")[0].lower(), \
        "the players heading has no suffix"
    host_pos = players_page.find("Ada")
    add_pos = players_page.find("Add a player")
    assert host_pos != -1 and add_pos != -1
    assert host_pos < add_pos, "the host comes first, then Add a player"
    assert "ada@example.com" in players_page, \
        "the host's own players page shows their own email"
    between = players_page[host_pos:add_pos]
    assert "<p>Each tap" not in between and "instruction" not in between.lower(), \
        "no instructions between the host and Add a player"


def test_continue_back_looks_like_a_button(live_forum):
    base, _service = live_forum
    _, coming, _ = http_get(base + "/continue")
    back = re.search(r'<a[^>]*href="/"[^>]*>\u2190 Back</a>', coming)
    assert back, coming[-500:]
    assert 'class="' in back.group(0) and "button" in back.group(0), \
        "the Continue Back control keeps its plain link but wears the" \
        " stylesheet's button look"
    status, css, _ = http_get(base + "/static/forum.css")
    assert status == 200
    assert "a.button" in css, \
        "the stylesheet gives the Back link the button look"


def test_symposium_page_uses_canonical_definitions_and_title_case(live_forum):
    base, _service = live_forum
    _players_page, tokens, sid = start_and_tokens(
        base, guests=1, symposium_name="Friday Philosophers",
        word="justice")
    host_token, guest = tokens["Ada"], tokens["Bohdan"]
    _, form, _ = http_get(base + f"/join/{guest}")
    # The join form is headed by the Symposium's name in Title Case,
    # never the raw lower word.
    assert "<h1>Friday Philosophers</h1>" in form, \
        "the join header is Title Case"
    assert "<h1>justice</h1>" not in form
    join_all(base, tokens)
    enter(base, host_token)
    _, symposium, _ = http_get(base + f"/symposiums/{sid}?token={host_token}")
    assert "<h2>Canonical Definitions</h2>" in symposium
    assert "Definitions from the dictionaries" not in symposium


def test_every_header_is_in_title_case(live_forum):
    base, _service = live_forum
    players_page, tokens, sid = start_and_tokens(base, guests=1)
    players_page_url = players_url(base, sid, tokens["Ada"])
    host_token, player_token = tokens["Ada"], tokens["Bohdan"]
    join_all(base, tokens)
    enter(base, host_token)
    pages = {}
    for label, url in (("landing", base + "/"),
                        ("start", base + "/start"),
                        ("continue", base + "/continue"),
                        ("players", players_page_url),
                        ("join", base + f"/join/{player_token}"),
                        ("symposium", base + f"/symposiums/{sid}?token={host_token}")):
        _, body, _ = http_get(url)
        pages[label] = body
    for label, body in pages.items():
        for header in re.findall(r"<h[123]>(.*?)</h[123]>", body, re.S):
            text = re.sub(r"<[^>]*>", "", header).strip()
            assert text[:1].isupper(), \
                f"the {label} header {text!r} is in Title Case"
            for word in re.sub(r"[^A-Za-z ]", "", text).split():
                if word.lower() in ("a", "an", "the", "and", "or", "of", "from", "to", "in", "on"):
                    continue
                assert word[:1].isupper(), \
                    f"the {label} header {text!r} is in Title Case"
    assert "Canonical Definitions" in pages["symposium"], \
        "the Symposium page lists Canonical Definitions"
    assert "Definitions from the dictionaries" not in pages["symposium"]


def test_setting_tooltips_show_the_same_text_on_hover(live_forum):
    base, _service = live_forum
    _, start, _ = http_get(base + "/start")
    titles = re.findall(r'<button[^>]*class="tip"[^>]*title="([^"]+)"',
                        start)
    texts = re.findall(r'class="tip-text"[^>]*>(.*?)</span>', start, re.S)
    assert len(titles) >= 3 and len(texts) >= 3
    assert titles == [html.unescape(t) for t in texts], \
        "each ? button carries the same hover text as its tap text"


def test_symposium_name_keeps_small_words_and_inner_capitals(live_forum):
    base, _service = live_forum
    players_page_url, _host, _sid = start_on_players(
        base, symposium_name="iPhone users of the night")
    _, players_page, _ = http_get(players_page_url)
    assert "<h1>iPhone Users of the Night</h1>" in players_page, \
        "the players page heads with the Symposium's name in Title Case " \
        "without changing what the host typed"
    assert "IPhone" not in players_page
    assert " Of The " not in players_page


def test_player_row_reads_the_players_name_once_they_join(live_forum):
    base, _service = live_forum
    before, tokens, sid = start_and_tokens(base, guests=1)
    players_page_url = players_url(base, sid, tokens["Ada"])
    assert before.count('class="who">Invited') == 1
    guest = tokens["Bohdan"]
    status, _page, _headers = join(
        base, guest, name="Bohdan", email="bohdan@example.com",
        color=PLAYER_COLORS[0][1])
    assert status == 303
    _, after, _ = http_get(players_page_url)
    assert 'class="who">Invited' not in after, \
        "the row reads the player's name instead of Invited"
    assert "Bohdan" in after
    assert "bohdan@example.com" not in after
