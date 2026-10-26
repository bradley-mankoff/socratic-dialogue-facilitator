"""Forum web server: start a Symposium in Symposia from a phone.

Stdlib only: ``http.server`` request handling, plain server-rendered pages
and forms, no dependencies, one phone-first stylesheet, and a thumbnail of
JavaScript (each player's Share button opens the phone's own share menu,
copying the message where the browser has none). One command starts it on
the host Mac::

    python -m web.forum

On screen it is always Symposia, never anything else. The landing page
splits into Start a Symposium (the start screen: the host's own name and
email, then a Settings box with the Symposium's name, the word and an
Anonymous Mode toggle, off by default) and Continue a Symposium (a
placeholder until Bead sdf-zj6.15 fills it). Pressing Start opens the
Symposium at once on the players page, headed by the Symposium's name;
there is no Begin button. The host never enters players' names or emails:
each tap on "Add a player" makes one row reading "Invited" with a note
field and a Share button, and players name themselves on arrival. One
Share message carries the row's note and then the player's personal link.
A link carries no protection: opening it signs that browser in as that
player, with no password. The first visit shows a short welcome page. No
page ever shows anyone's email but the host's own on the host's own
players page, and no page says room.

Inside, the definitions page lists what the dictionaries say, each ending
with a small linked source note like "(Wiktionary)". License and access
date stay recorded but are not shown, and wiki markup is stripped where the
dictionary chain parses Wiktionary. The first person to claim either picks
one of those definitions (copied and tagged with its source) or writes
their own, and it becomes the active definition. After that the claim form
is gone; a second claim is refused with a plain message before the first
mutation. Revising and switching belong to later Beads, so this page offers
no path for either.

Every person-reachable path ends in a working page: mistakes re-render the
same form with a plain-words notice and the person's inputs kept — except
the host's email, which is never echoed back — never an
error page. Visible pages never show anyone's email, machine ids
(node, question or handle ids, sense ids, underscore names), or controls
that exist only for testing. Sense ids travel only inside form values.
"""

from __future__ import annotations

import argparse
import html
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dictionary.normalize import normalize_x
from server.model import now_iso as _now
from server.symposium import (
    SymposiumStore,
    host_key,
    valid_email,
)

COOKIE_NAME = "sdf_token"
# One year: the host's way back to their players page (and a guest's way
# back in) survives the browser closing. Without it the cookie is gone
# when the browser closes and the players page has no way back.
COOKIE_MAX_AGE = 365 * 24 * 60 * 60

# One phone-first stylesheet for every forum page: a narrow column a
# thumb can work, readable at phone width without zooming, with tap
# targets at least 44 pixels high, nothing wider than the screen, and a
# centered column so a wide screen stays tidy too.
FORUM_CSS = """
* { box-sizing: border-box; }
html, body {
  overflow-x: hidden;
  max-width: 100%;
}
body {
  margin: 0 auto;
  max-width: 34rem;
  padding: 0 1rem 3rem;
  font-size: 18px;
  line-height: 1.5;
  font-family: -apple-system, system-ui, sans-serif;
  overflow-wrap: break-word;
}
button, input[type="submit"], a.button {
  min-height: 44px;
  min-width: 44px;
  font-size: 1.1rem;
  padding: 0.5rem 1rem;
}
a.button {
  display: inline-block;
  border: 1px solid currentColor;
  border-radius: 0.25rem;
  text-decoration: none;
  color: inherit;
  line-height: calc(44px - 1rem);
}
input[type="text"], textarea {
  width: 100%;
  max-width: 100%;
  min-height: 44px;
  font-size: 1rem;
}
input[readonly] { font-size: 1rem; }
pre { max-width: 100%; overflow-x: auto; }
ul { padding-left: 1.2rem; }
li { margin-bottom: 1rem; }
.notice {
  border: 2px solid currentColor;
  padding: 0.75rem;
}
""".encode("utf-8")


def _notice_html(notice: str | None) -> str:
    if not notice:
        return ""
    return f"<p class=\"notice\">{html.escape(notice)}</p>\n"


def _page(title: str, body: str) -> bytes:
    return ("<!DOCTYPE html>\n<html lang=\"en\">\n<head>"
            "<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" "
            "content=\"width=device-width, initial-scale=1\">\n"
            "<link rel=\"stylesheet\" href=\"/static/forum.css\">\n"
            f"<title>{html.escape(title)}</title></head>\n<body>\n"
            f"{body}\n</body>\n</html>\n").encode("utf-8")


# The one placeholder a page may show for a participant with no public
# name yet (an unjoined slot with Anonymous Mode off, anyone with
# Anonymous Mode on until random animals arrive in sdf-zj6.3). Owned here
# beside the one renderer so no page can print an internal suffix like
# Guest#2.
_GUEST_DISPLAY = "Guest"
# The display name a board handle is enrolled under for a guest who has
# not joined and named themselves (a later Bead binds their name). Kept
# separate from the page placeholder on purpose: the board may uniquify
# it ("Guest slot#2"), and no such internal name may ever reach a page.
_PROVISIONAL_DISPLAY = "Guest slot"


def _display_name(record: dict, person: dict) -> str:
    """What one participant is called on a page.

    Anonymous Mode off: their name, else a guest placeholder.
    Anonymous Mode on: always the placeholder — no page can leak a name
    with Anonymous Mode on. Random animals arrive in sdf-zj6.3; until
    then anonymous means no name anywhere, not even the host's."""
    if record.get("anonymous"):
        return _GUEST_DISPLAY
    return person.get("name") or _GUEST_DISPLAY


def _joined_names(record: dict, exclude_token: str = "") -> list[str]:
    """What the joined participants are called, via the one renderer.

    Only joined participants appear, so unjoined invitation slots never
    read as people; with Anonymous Mode on the joined show as the Guest
    placeholder. The welcome page, the Symposium page and the start
    page's list of who is in all build on this one helper."""
    return [_display_name(record, p) for p in record["participants"]
            if p.get("joined") and p["token"] != exclude_token]


_SMALL_WORDS = frozenset({
    "a", "an", "the", "and", "or", "of", "from",
    "to", "in", "on",
})


def _title_case(text: str) -> str:
    """Title Case for user content shown as a header.

    Small words stay lower unless first; words with capitals inside
    (iPhone) stay as the host typed them, so Title Case never rewrites
    a name into IPhone or Of The."""
    words = str(text).split()
    titled = []
    for i, word in enumerate(words):
        lowered = word.lower()
        if i > 0 and lowered in _SMALL_WORDS:
            titled.append(lowered)
        elif any(c.isupper() for c in word[1:]):
            titled.append(word)
        elif word:
            titled.append(word[:1].upper() + word[1:])
        else:
            titled.append(word)
    return " ".join(titled)


def _host_way_back(store, headers) -> str:
    """The host's visible way back to their players page, if signed in.

    Named for their Symposium, so a signed-in host knows whose page it
    opens; shown only on the Continue page until Bead sdf-zj6.15 lists
    Symposia there."""
    token = _cookie_token(headers)
    if not token:
        return ""
    record, person = store.get_by_token(token)
    if record is None or person is None or not person.get("is_host"):
        return ""
    url = _players_url(record["board_id"], person["token"])
    name = html.escape(_symposium_heading(record))
    return (f"<p><a class=\"button\" href=\"{url}\">"
            f"Back to {name}</a></p>\n")


def _symposium_heading(record: dict) -> str:
    """The Symposium's name for a page header, in Title Case."""
    return _title_case(record.get("name", ""))


def _landing_page() -> bytes:
    """The landing page: Symposia, with Start and Continue paths.

    Two large buttons and nothing else: each choice appears once, so
    no heading repeats the link's words."""
    body = (
        "<h1>Symposia</h1>\n"
        "<p><a class=\"button\" href=\"/start\">"
        "Start a Symposium</a></p>\n"
        "<p><a class=\"button\" href=\"/continue\">"
        "Continue a Symposium</a></p>\n")
    return _page("Symposia", body)


def _continue_page(way_back: str = "") -> bytes:
    """Placeholder until Bead sdf-zj6.15 fills in Continue by email."""
    body = (
        "<h1>Symposia</h1>\n"
        "<h2>Continue a Symposium</h2>\n"
        "<p>Continuing a Symposium is coming. "
        "Ask the host for your personal link for now.</p>\n"
        + way_back +
        "<p><a class=\"button\" href=\"/\">\u2190 Back</a></p>\n")
    return _page("Symposia", body)


# Tooltips for the three Settings, one fixed text each: the same text
# whatever the setting's position (the Anonymous Mode tooltip reads the
# same on and off).
_SYMPOSIUM_NAME_TIP = ("The name everyone sees for this Symposium, "
                       "such as Friday Philosophers.")
_WORD_TIP = "The word the group will define together."
_ANONYMOUS_TIP = ("On, everyone appears as a random animal and votes "
                  "are anonymous. Off, everyone appears by name and "
                  "votes show who voted which way.")


def _tip(setting: str, text: str) -> str:
    """One phone-tappable tooltip: a button outside any label.

    The button carries the same text as a hover title and as the tap
    text beside it: computers show it on hover, phones show it on tap."""
    return (
        f'<button type="button" class="tip" '
        f'title="{html.escape(text, quote=True)}" '
        f'aria-label="About {html.escape(setting)}">?</button> '
        f'<span class="tip-text" hidden>{html.escape(text)}</span>')


def _start_page(notice: str | None = None, *,
                host_name: str = "", symposium_name: str = "",
                word: str = "", anonymous: bool = False) -> bytes:
    body = (
        "<h1>Symposia</h1>\n"
        "<h2>Start a Symposium</h2>\n"
        + _notice_html(notice) +
        "<form method=\"post\" action=\"/start\">\n"
        "<p><label for=\"host_name\">Your Name</label> "
        "<input type=\"text\" id=\"host_name\" name=\"host_name\" "
        f"value=\"{html.escape(host_name, quote=True)}\"></p>\n"
        "<p><label for=\"host_email\">Your Email</label> "
        "<input type=\"text\" id=\"host_email\" name=\"host_email\" "
        "autocomplete=\"email\"></p>\n"
        "<fieldset><legend>Settings</legend>\n"
        "<p><label for=\"symposium_name\">Symposium Name</label> "
        + _tip("Symposium Name", _SYMPOSIUM_NAME_TIP) +
        " <input type=\"text\" id=\"symposium_name\" "
        "name=\"symposium_name\" "
        f"value=\"{html.escape(symposium_name, quote=True)}\"></p>\n"
        "<p><label for=\"word\">Word</label> "
        + _tip("Word", _WORD_TIP) +
        " <input type=\"text\" id=\"word\" name=\"word\" "
        f"value=\"{html.escape(word, quote=True)}\"></p>\n"
        "<p><label for=\"anonymous\">Anonymous Mode</label> "
        + _tip("Anonymous Mode", _ANONYMOUS_TIP) +
        " <input type=\"checkbox\" id=\"anonymous\" "
        "name=\"anonymous\" value=\"on\""
        + (" checked" if anonymous else "") + "></p>\n"
        "</fieldset>\n"
        "<p><button type=\"submit\">Start</button></p>\n"
        "</form>\n"
        "<script>\n"
        "(function () {\n"
        "  Array.prototype.forEach.call(\n"
        "    document.querySelectorAll('button.tip'), function (button) {\n"
        "      button.addEventListener('click', function () {\n"
        "        var text = button.nextElementSibling;\n"
        "        if (text && text.classList.contains('tip-text')) {\n"
        "          text.hidden = !text.hidden;\n"
        "        }\n"
        "      });\n"
        "    });\n"
        "})();\n"
        "</script>\n")
    return _page("Symposia", body)


_SOURCE_NAMES = {
    "wiktionary": "Wiktionary",
    "free-dictionary": "Free Dictionary",
    "merriam-webster": "Merriam-Webster",
}


def _source_display(source: str) -> str:
    """Readable source name: slugs never reach the page."""
    return _SOURCE_NAMES.get(source, source.replace("-", " ").title())


def _source_note(cites: list[dict]) -> str:
    """One small linked parenthetical per definition, e.g. (Wiktionary)."""
    if not cites:
        return ""
    cite = cites[0]
    url = html.escape(str(cite.get("url", "")), quote=True)
    name = html.escape(_source_display(str(cite.get("source", ""))))
    return f' <small><a href="{url}">({name})</a></small>'


def _definitions_section(snapshot: dict | None) -> str:
    if snapshot is None:
        return "<p>Definitions have not been pulled yet.</p>"
    if snapshot.get("state") == "empty":
        if snapshot.get("empty_reason") == "all_sources_unavailable":
            return ("<p>The dictionary sources could not be reached. "
                    "Please try again later. What you see here is an "
                    "outage, not a consensus: no definitions are shown "
                    "because none could be fetched.</p>")
        return "<p>No dictionary definitions were found for this word.</p>"
    parts = ["<h2>Canonical Definitions</h2>", "<ol>"]
    for sense in snapshot.get("senses", []):
        pos = sense.get("pos")
        pos_line = f" ({html.escape(str(pos))})" if pos else ""
        parts.append(
            f"<li>Definition{pos_line}: "
            f"{html.escape(str(sense.get('gloss', '')))}"
            f"{_source_note(sense.get('cites', []))}</li>")
    parts.append("</ol>")
    return "\n".join(parts)


def _attempts_section(service, record: dict) -> str:
    state = service.state(record["board_id"])
    nodes = sorted(state.nodes.values(), key=lambda n: n.version)
    if not nodes:
        return ("<h2>Active Definition</h2>\n"
                "<p>No active definition yet — "
                "pick or write the first one below.</p>")
    provenances = service.provenance_map(record["board_id"])
    # Every name on every page goes through the one rendering function:
    # a board handle means nothing on screen until it is matched to its
    # participant, so internal suffixes (Guest#2) and names with
    # Anonymous Mode on (Ada) can never leak through the definitions list.
    by_handle = {p.get("handle_id"): p for p in record["participants"]
                 if p.get("handle_id")}
    parts = ["<h2>Active Definition</h2>", "<ol>"]
    for node in nodes:
        provenance = provenances.get(node.node_id, {})
        handle_id = provenance.get("claimed_by", node.defender)
        person = by_handle.get(handle_id)
        name = (_display_name(record, person)
                if person is not None else _GUEST_DISPLAY)
        marker = " (active)" if node.is_active else ""
        if provenance.get("kind") == "canonical":
            sources = ", ".join(
                _source_display(str(s))
                for s in provenance.get("cite_sources", []))
            tag = ("Copied from the dictionary"
                   + (f" ({sources})" if sources else "")
                   + ". ")
        else:
            tag = f"Written by {html.escape(name)}. "
        parts.append(
            f"<li>Attempt {node.version}{html.escape(marker)}: "
            f"{html.escape(node.text)}<br>{tag}"
            f"Held by {html.escape(name)}.</li>")
    parts.append("</ol>")
    return "\n".join(parts)


def _symposium_prefix(board_id: str) -> str:
    """The ``/symposiums/<id>`` path prefix, quoted once, in one place."""
    return "/symposiums/" + urllib.parse.quote(board_id, safe="")


def _claim_form(record: dict, person: dict, snapshot: dict | None,
                sense: str = "", original: str = "") -> str:
    action = _symposium_prefix(record["board_id"]) + "/claim"
    picks = []
    if snapshot and snapshot.get("state") == "ok":
        picks.append("<p>Pick one:</p>")
        for item in snapshot.get("senses", []):
            value = html.escape(str(item.get("sense_id", "")), quote=True)
            checked = (" checked"
                       if str(item.get("sense_id")) == sense else "")
            gloss = html.escape(str(item.get("gloss", "")))
            picks.append(
                f"<p><label><input type=\"radio\" name=\"sense\" "
                f"value=\"{value}\"{checked}> {gloss}</label></p>")
    shown = _display_name(record, person)
    return (
        "<h2>Claim the Definition</h2>\n"
        f"<p>Claiming as {html.escape(shown)}.</p>\n"
        f"<form method=\"post\" action=\"{action}\">\n"
        "<input type=\"hidden\" name=\"token\" "
        f"value=\"{html.escape(person['token'], quote=True)}\">\n"
        + "\n".join(picks) +
        "<p>Or write your own:</p>\n"
        "<p><textarea name=\"original\" rows=\"3\" cols=\"60\">"
        f"{html.escape(original)}</textarea></p>\n"
        "<p><button type=\"submit\">Claim this definition</button></p>\n"
        "</form>")


def _symposium_page(service, record: dict, person: dict,
                    notice: str | None = None, sense: str = "",
                    original: str = "") -> bytes:
    snapshot = service.canonicals(record["board_id"])
    state = service.state(record["board_id"])
    claim = ""
    if state.active_node_id is None:
        claim = _claim_form(record, person, snapshot, sense, original)
    others = _joined_names(record, exclude_token=person["token"])
    company = (" with " + ", ".join(html.escape(n) for n in others)
               if others else "")
    players_link = ""
    if person.get("is_host"):
        players_url = _players_url(record["board_id"], person["token"])
        players_link = (f"<p><a href=\"{players_url}\">Players</a> "
                       "(the host's page: add players and share "
                       "their links).</p>\n")
    heading = html.escape(_symposium_heading(record))
    body = (
        f"<h1>{heading}</h1>\n"
        f"<p>A Symposium on {html.escape(record['word'])}"
        f"{company}.</p>\n"
        + _notice_html(notice)
        + _definitions_section(snapshot)
        + _attempts_section(service, record)
        + claim
        + players_link)
    return _page("Symposia", body)


def _share_message(note: str, link: str) -> str:
    """The one Share message: the saved note, then the personal link.

    The server alone builds it, in exactly one place: the players page
    carries it on each Share button and the note endpoint answers with
    it, so the phone shares or copies the same text either way. An empty
    note shares the link alone."""
    saved = str(note or "")
    return (saved + "\n" + link) if saved else link


def _join_link(base_url: str, token: str) -> str:
    """One personal link, built from the forum's address, in one place."""
    return base_url.rstrip("/") + "/join/" + token


def _share_message_attr(message: str) -> str:
    """One Share message escaped for a button's data-message attribute."""
    return html.escape(message, quote=True).replace("\n", "&#10;")


def _players_action_url(board_id: str, leaf: str) -> str:
    """POST path for the host's players actions (``add`` or ``note``)."""
    return _symposium_prefix(board_id) + "/players/" + leaf


def _players_page(record: dict, host: dict, base_url: str,
                 notice: str | None = None) -> bytes:
    """The host's players page: one personal link per tap on Add a player.

    Headed by the Symposium's name, with no suffix. The host comes first
    with their name and email, then the Add a player button, with nothing
    in between. Each tap adds one row reading "Invited", with a note
    field and a Share button and no Copy button. No raw link is shown:
    each Share button carries the server-built message for its row's
    saved note (the note, then the player's personal link, built from
    ``base_url``), so tapping Share reads it straight away with no
    request in between — a phone's share menu only opens inside the tap
    itself. Where the browser has no share function, the same button
    copies that message and says "Copied". The host enters nothing
    else about a human player. No page here shows anyone's email but
    the host's own."""
    name = _symposium_heading(record)
    rows = []
    for person in record["participants"]:
        if person.get("is_host"):
            continue
        note = person.get("note") or ""
        link = _join_link(base_url, person["token"])
        message = _share_message_attr(_share_message(note, link))
        status = "Joined" if person.get("joined") else "Invited"
        note_action = _players_action_url(record["board_id"], "note")
        rows.append(
            f"<li><span class=\"who\">{status}</span><br>"
            "<button type=\"button\" class=\"share\" "
            f"data-player=\"{html.escape(person['token'], quote=True)}\" "
            f"data-message=\"{message}\" "
            f"data-note-url=\"{html.escape(note_action, quote=True)}\" "
            f"data-token=\"{html.escape(host['token'], quote=True)}\">"
            "Share</button> "
            "<span class=\"copied\" aria-live=\"polite\"></span><br>"
            f"<form method=\"post\" action=\"{note_action}\">\n"
            "<input type=\"hidden\" name=\"token\" "
            f"value=\"{html.escape(host['token'], quote=True)}\">\n"
            "<input type=\"hidden\" name=\"player\" "
            f"value=\"{html.escape(person['token'], quote=True)}\">\n"
            "<label>Note "
            "<input type=\"text\" name=\"note\" "
            f"value=\"{html.escape(note, quote=True)}\" "
            "placeholder=\"Note to send with the link\"></label>"
            "</form></li>")
    listing = ("<ul>\n" + "\n".join(rows) + "\n</ul>" if rows
               else "")
    add_action = _players_action_url(record["board_id"], "add")
    in_url = _symposium_url(record["board_id"], host["token"])
    host_name = host.get("name") or ""
    host_email = host.get("email") or ""
    body = (
        f"<h1>{html.escape(name)}</h1>\n"
        f"<p>{html.escape(host_name)} — {html.escape(host_email)}</p>\n"
        f"<form method=\"post\" action=\"{add_action}\">\n"
        "<input type=\"hidden\" name=\"token\" "
        f"value=\"{html.escape(host['token'], quote=True)}\">\n"
        "<p><button type=\"submit\">Add a player</button></p>\n"
        "</form>\n"
        + _notice_html(notice)
        + listing + "\n"
        "<script>\n"
        "(function () {\n"
        "  Array.prototype.forEach.call(\n"
        "    document.querySelectorAll('button.share'), function (button) {\n"
        "      var host = button.dataset.token || '';\n"
        "      var player = button.dataset.player || '';\n"
        "      var noteUrl = button.dataset.noteUrl || '';\n"
        "      // Tapping Share reads the button's carried message straight\n"
        "      // away, with no request in between: a phone's share menu\n"
        "      // only opens inside the tap itself.\n"
        "      button.addEventListener('click', function () {\n"
        "        var message = button.dataset.message || '';\n"
        "        var row = rowOf(button);\n"
        "        sayIn(row, '');\n"
        "        if (navigator.share) {\n"
        "          navigator.share({text: message})\n"
        "            .catch(function (err) {\n"
        "              if (err && err.name === 'AbortError') { return; }\n"
        "              copyOf(row, message);\n"
        "            });\n"
        "        } else {\n"
        "          copyOf(row, message);\n"
        "        }\n"
        "      });\n"
        "      // Typing in the note field saves it in the background\n"
        "      // shortly after typing stops; the answer replaces the\n"
        "      // button's carried message. Overlapping saves settle in\n"
        "      // order: each edit takes a sequence number at once, and an\n"
        "      // answer that is not the latest edit's is ignored, so a stale\n"
        "      // answer can neither re-enable Share nor replace a newer\n"
        "      // message. The button stays disabled until the latest edit's\n"
        "      // save settles.\n"
        "      var row = rowOf(button);\n"
        "      var field = row ? row.querySelector(\n"
        "        'input[name=\"note\"]') : null;\n"
        "      if (field) {\n"
        "        var timer = null;\n"
        "        var latest = 0;\n"
        "        field.addEventListener('input', function () {\n"
        "          if (timer) { clearTimeout(timer); }\n"
        "          latest += 1;\n"
        "          var mine = latest;\n"
        "          button.disabled = true;\n"
        "          button.textContent = 'Saving...';\n"
        "          sayIn(row, '');\n"
        "          timer = setTimeout(function () {\n"
        "            var body = 'token=' + encodeURIComponent(host)\n"
        "              + '&player=' + encodeURIComponent(player)\n"
        "              + '&note=' + encodeURIComponent(field.value || '');\n"
        "            fetch(noteUrl, {method: 'POST', headers: {\n"
        "              'Content-Type': 'application/x-www-form-urlencoded',\n"
        "              'Accept': 'text/plain'}, body: body})\n"
        "              .then(function (resp) {\n"
        "                var kind = resp.headers.get('Content-Type') || '';\n"
        "                if (!resp.ok || kind.indexOf('text/plain') === -1) {\n"
        "                  throw new Error('save failed');\n"
        "                }\n"
        "                return resp.text();\n"
        "              })\n"
        "              .then(function (message) {\n"
        "                if (mine !== latest) { return; }\n"
        "                button.dataset.message = message;\n"
        "                button.disabled = false;\n"
        "                button.textContent = 'Share';\n"
        "                sayIn(row, '');\n"
        "              })\n"
        "              .catch(function () {\n"
        "                if (mine !== latest) { return; }\n"
        "                button.disabled = false;\n"
        "                button.textContent = 'Share';\n"
        "                sayIn(row,\n"
        "                  'Could not save the note. Try again.');\n"
        "              });\n"
        "          }, 600);\n"
        "        });\n"
        "      }\n"
        "    });\n"
        "  function rowOf(button) {\n"
        "    return button.closest ? button.closest('li')\n"
        "      : button.parentElement;\n"
        "  }\n"
        "  function sayIn(row, text) {\n"
        "    var note = row ? row.querySelector('.copied') : null;\n"
        "    if (note) { note.textContent = text; }\n"
        "  }\n"
        "  function copyOf(row, message) {\n"
        "    function say(text) { sayIn(row, text); }\n"
        "    function legacyCopy() {\n"
        "      try {\n"
        "        var area = document.createElement('textarea');\n"
        "        area.value = message;\n"
        "        document.body.appendChild(area);\n"
        "        area.select();\n"
        "        var ok = document.execCommand('copy');\n"
        "        document.body.removeChild(area);\n"
        "        if (ok) { say('Copied'); return; }\n"
        "      } catch (e) {}\n"
        "      say('Copy this message by hand');\n"
        "    }\n"
        "    if (navigator.clipboard && navigator.clipboard.writeText) {\n"
        "      navigator.clipboard.writeText(message).then(\n"
        "        function () { say('Copied'); },\n"
        "        function () { legacyCopy(); });\n"
        "    } else {\n"
        "      legacyCopy();\n"
        "    }\n"
        "  }\n"
        "})();\n"
        "</script>\n"
        f"<p><a href=\"{in_url}\">Go to the Symposium</a></p>\n")
    return _page("Symposia", body)


def _welcome_page(record: dict, person: dict) -> bytes:
    # Every name on this page goes through the one rendering function:
    # the greeting names nobody, and the company list names only joined
    # participants through _display_name, so no branch here can leak
    # a name with Anonymous Mode on.
    others = _joined_names(record, exclude_token=person["token"])
    action = "/join/" + person["token"] + "/enter"
    body = (
        f"<h1>{html.escape(_title_case(record['word']))}</h1>\n"
        "<p>Welcome.</p>\n"
        "<p>You are joining a Symposium on "
        f"{html.escape(record['word'])}"
        + (" with " + ", ".join(html.escape(n) for n in others) + "."
           if others else ", just you for now.") + "</p>\n"
        "<p>Everyone takes turns putting forward a definition "
        "and defending it.</p>\n"
        "<p>Everyone takes turns offering a counterexample "
        "against it.</p>\n"
        "<p>The group votes on each counterexample, and on when to set "
        "a definition aside and move on.</p>\n"
        f"<form method=\"post\" action=\"{action}\">\n"
        "<p><button type=\"submit\">Go in</button></p>\n"
        "</form>")
    return _page("Symposia", body)


def _symposium_url(board_id: str, token: str) -> str:
    """Relative path to one person's Symposium page."""
    return (_symposium_prefix(board_id)
            + "?token=" + urllib.parse.quote(token, safe=""))


def _players_url(board_id: str, token: str) -> str:
    """Relative path to the host's players page for one Symposium."""
    return (_symposium_prefix(board_id)
            + "/players?token=" + urllib.parse.quote(token, safe=""))


def _base_url(headers) -> str:
    """Absolute base (scheme + Host) for invitation links.

    Personal links must paste into Messages or Mail as something a guest
    can open, so they are built from the request's Host header until
    sdf-mgt.22 supplies the fixed Tailscale address. Behind Tailscale
    Funnel the proxy passes its scheme in X-Forwarded-Proto."""
    host = str(headers.get("Host", "")).strip()
    proto = str(headers.get("X-Forwarded-Proto", ""))
    scheme = proto.split(",")[0].strip().lower() or "http"
    if scheme not in ("http", "https"):
        scheme = "http"
    if not host:
        host = "127.0.0.1"
    return f"{scheme}://{host}"


def _cookie_token(headers) -> str:
    """The forum's signed-in token from the Cookie header, or empty."""
    cookie = str(headers.get("Cookie", ""))
    for chunk in cookie.split(";"):
        name, _, value = chunk.partition("=")
        if name.strip() == COOKIE_NAME:
            return value.strip()
    return ""


def _token_from(query: dict, headers) -> str:
    values = query.get("token", [])
    if values:
        return values[0]
    return _cookie_token(headers)


def make_handler(service):
    """Build a stdlib request-handler class bound to one ``BoardService``."""
    store = SymposiumStore(service.root)
    # One Mac, one forum process: every request that changes anything
    # goes through this lock one at a time, while pages that only read
    # (do_GET) never take it and stay parallel. A plain Lock is enough:
    # no handler ever takes it twice (the body is read before it is taken
    # and _routed_post never re-enters).
    mutation_lock = threading.Lock()

    class ForumHandler(BaseHTTPRequestHandler):
        server_version = "Forum/1"

        def log_message(self, *args):  # quiet under tests
            pass

        # -- routing --------------------------------------------------
        def do_GET(self):
            try:
                self._routed_get()
            except Exception:
                self._send(200, _start_page(
                    "That page is not available right now. Start here."))

        def _routed_get(self):
            parts = urllib.parse.urlsplit(self.path)
            path = parts.path
            query = urllib.parse.parse_qs(parts.query)
            if path == "/":
                self._send(200, _landing_page())
                return
            if path == "/start":
                self._send(200, _start_page())
                return
            if path == "/continue":
                way_back = _host_way_back(store, self.headers)
                self._send(200, _continue_page(way_back))
                return
            if path == "/static/forum.css":
                self._send(200, FORUM_CSS, "text/css; charset=utf-8")
                return
            segs = path.strip("/").split("/")
            if len(segs) == 2 and segs[0] == "join":
                self._handle_join(urllib.parse.unquote(segs[1]))
                return
            if (len(segs) == 3 and segs[0] == "symposiums"
                    and segs[2] == "players"):
                self._handle_players(urllib.parse.unquote(segs[1]),
                                    query)
                return
            if len(segs) == 2 and segs[0] == "symposiums":
                self._handle_symposium(urllib.parse.unquote(segs[1]), query)
                return
            self._send(
                200, _start_page("That page does not exist. Start here."))

        def do_POST(self):
            # Read the slow body before taking the lock, so one slow
            # phone never holds up every other change while it uploads.
            parts = urllib.parse.urlsplit(self.path)
            length = self.headers.get("Content-Length")
            try:
                size = int(length) if length is not None else 0
            except ValueError:
                size = 0
            raw = self.rfile.read(size) if size > 0 else b""
            # Every POST changes something (or tries to), so the routing
            # below goes through the mutation lock one at a time. Reads
            # (do_GET) never take it. Later Beads add more POST routes;
            # they inherit the same guarantee because the lock sits here,
            # not per route.
            try:
                with mutation_lock:
                    self._routed_post(parts.path, raw)
            except Exception:
                self._send(200, _start_page(
                    "That request could not be completed. Start here."))

        def _routed_post(self, path: str, raw: bytes):
            fields = urllib.parse.parse_qs(raw.decode("utf-8", "replace"))

            def field(name: str) -> str:
                values = fields.get(name, [])
                return values[0] if values else ""

            if path == "/start":
                self._handle_start(field("host_name"), field("host_email"),
                                   field("symposium_name"), field("word"),
                                   field("anonymous"))
                return
            segs = path.strip("/").split("/")
            if (len(segs) == 4 and segs[0] == "symposiums"
                    and segs[2] == "players" and segs[3] == "add"):
                self._handle_players_add(urllib.parse.unquote(segs[1]),
                                        field("token"))
                return
            if (len(segs) == 4 and segs[0] == "symposiums"
                    and segs[2] == "players" and segs[3] == "note"):
                self._handle_players_note(urllib.parse.unquote(segs[1]),
                                         field("token"),
                                         field("player"),
                                         field("note"))
                return
            if (len(segs) == 3 and segs[0] == "join"
                    and segs[2] == "enter"):
                self._handle_enter(urllib.parse.unquote(segs[1]))
                return
            if (len(segs) == 3 and segs[0] == "symposiums"
                    and segs[2] == "claim"):
                self._handle_claim(urllib.parse.unquote(segs[1]),
                                   field("token"), field("sense"),
                                   field("original"))
                return
            self._send(
                200, _start_page("That page does not exist. Start here."))

        # -- the start form: host, Settings (name, word, Anonymous Mode) --
        def _handle_start(self, host_name: str, host_email: str,
                          symposium_name: str, word: str,
                          anonymous: str):
            host_name, host_email = host_name.strip(), host_email.strip()
            symposium_name = symposium_name.strip()
            word = word.strip()
            # The checkbox sends "on" when ticked, nothing when unticked.
            is_anonymous = anonymous.strip().lower() == "on"

            def rerender(notice: str) -> None:
                # The host's email is never echoed back: no page shows it.
                self._send(200, _start_page(
                    notice, host_name=host_name,
                    symposium_name=symposium_name,
                    word=word, anonymous=is_anonymous))

            if not host_name:
                rerender("Please type your name first, so people know "
                         "who invited them.")
                return
            if not valid_email(host_email):
                rerender("Please type your email as name@example.com, "
                         "so turn and vote emails can reach you.")
                return
            if not symposium_name:
                rerender("Please name your Symposium, "
                         "so people know which one they are joining.")
                return
            if not word or not normalize_x(word):
                rerender("Please type the word this Symposium will define.")
                return
            # Every Start makes a new Symposium (the old rule of one open
            # Symposium per word and group went with the guest box). The
            # count of earlier Symposiums on this word with this host
            # numbers the next one ("Justice, second symposium").
            key = host_key(host_email)
            word_norm = normalize_x(word)
            ordinal = len(store.lineage(word_norm, key)) + 1
            try:
                opened = service.open_board(word, None)
            except Exception:
                rerender("That Symposium could not be opened. "
                         "Please try again.")
                return
            board_id = opened.board_id
            try:
                host_handle = service.machine(board_id).enroll_handle(
                    host_name)
            except Exception:
                rerender("That Symposium could not gather its players. "
                         "Please try again.")
                return
            record = store.create(
                board_id=board_id, word=word,
                players=[{"name": host_name, "email": host_email,
                         "is_host": True, "joined": True,
                         "handle_id": host_handle}],
                ordinal=ordinal, created_at=_now(),
                symposium_name=symposium_name, anonymous=is_anonymous)
            host_token = next(p["token"] for p in record["participants"]
                              if p["is_host"])
            self._set_cookie(host_token)
            self._redirect(_players_url(board_id, host_token))

        def _host_or_start(self, board_id: str, token: str):
            """The ``(record, host)`` pair, or ``(None, None)``."""
            record = store.get(board_id)
            if record is None:
                self._send(200, _start_page(
                    "That Symposium does not exist. Start it below."))
                return None, None
            found = next((p for p in record["participants"]
                          if p["token"] == token), None)
            if found is None:
                self._send(200, _start_page(
                    "That invitation link is not recognized. "
                           "Start here, or ask the host for your link."))
                return None, None
            if not found.get("is_host"):
                self._redirect(_symposium_url(record["board_id"],
                                              found["token"]))
                return None, None
            return record, found

        # -- the host's players page: add players, share links -------------
        def _handle_players(self, board_id: str, query: dict):
            token = _token_from(query, self.headers)
            record, host = self._host_or_start(board_id, token)
            if record is None:
                return
            self._send(200, _players_page(
                record, host, _base_url(self.headers)))

        def _handle_players_add(self, board_id: str, token: str):
            record, host = self._host_or_start(board_id, token)
            if record is None:
                return
            try:
                handle_id = service.machine(board_id).enroll_handle(
                    _PROVISIONAL_DISPLAY, kind="provisional")
                participant = store.add_player(board_id, handle_id=handle_id)
            except Exception:
                participant = None
            if participant is None:
                self._send(200, _players_page(
                    record, host, _base_url(self.headers),
                    "That player could not be added. Please try again."))
                return
            self._redirect(_players_url(board_id, host["token"]))

        def _handle_players_note(self, board_id: str, token: str,
                                player_token: str, note: str):
            record, host = self._host_or_start(board_id, token)
            if record is None:
                return
            saved_player = store.set_note(board_id, player_token, note)
            if saved_player is None:
                self._send(200, _players_page(
                    record, host, _base_url(self.headers),
                    "That note could not be saved. Please try again."))
                return
            # The server is the one builder of the Share message: the
            # players page carries it on each Share button, and the
            # background note save answers with it, so the script stores
            # the answer on the button for the next tap to share or copy.
            # A plain form posts without Accept and goes back to the
            # players page as before.
            accept = str(self.headers.get("Accept", ""))
            if "text/plain" in accept:
                saved = saved_player.get("note") or ""
                link = _join_link(_base_url(self.headers), player_token)
                message = _share_message(saved, link)
                self._send(200, message.encode("utf-8"),
                            "text/plain; charset=utf-8")
                return
            self._redirect(_players_url(board_id, host["token"]))

        # -- welcome, entering ------------------------------------------

        def _handle_join(self, token: str):
            record, person = store.get_by_token(token)
            if record is None or person is None:
                self._send(200, _start_page(
                    "That invitation link is not recognized. "
                           "Start here, or ask the host for your link."))
                return
            if person.get("joined"):
                self._redirect(_symposium_url(record["board_id"],
                                              person["token"]))
                return
            self._send(200, _welcome_page(record, person))

        def _handle_enter(self, token: str):
            record, person = store.get_by_token(token)
            if record is None or person is None:
                self._send(200, _start_page(
                    "That invitation link is not recognized. "
                           "Start here, or ask the host for your link."))
                return
            store.mark_joined(record["board_id"], token)
            self._set_cookie(token)
            self._redirect(_symposium_url(record["board_id"],
                                          person["token"]))

        # -- the Symposium page and its first claim ----------------------
        def _handle_symposium(self, board_id: str, query: dict):
            token = _token_from(query, self.headers)
            record = store.get(board_id)
            if record is None:
                self._send(200, _start_page(
                    "That Symposium does not exist. Start it below."))
                return
            person = next((p for p in record["participants"]
                           if p["token"] == token), None)
            if person is None:
                other, _ = store.get_by_token(token)
                if other is not None:
                    self._redirect(_symposium_url(other["board_id"], token))
                    return
                self._send(200, _start_page(
                    "That invitation link is not recognized. "
                           "Start here, or ask the host for your link."))
                return
            if not person.get("joined"):
                self._send(200, _welcome_page(record, person))
                return
            self._send(200, _symposium_page(service, record, person))

        def _handle_claim(self, board_id: str, token: str, sense_id: str,
                          original: str):
            record = store.get(board_id)
            if record is None:
                self._send(200, _start_page(
                    "That Symposium does not exist. Start it below."))
                return
            person = next((p for p in record["participants"]
                           if p["token"] == token), None)
            if person is None:
                self._send(200, _start_page(
                    "That invitation link is not recognized. "
                           "Start here, or ask the host for your link."))
                return
            if not person.get("joined"):
                self._send(200, _welcome_page(record, person))
                return
            sense_id, original = sense_id.strip(), original.strip()

            def rerender(notice: str, sense: str = sense_id,
                         text: str = original) -> None:
                self._send(200, _symposium_page(service, record, person,
                                                notice, sense, text))

            if sense_id and original:
                rerender("Please pick one or write one, not both — "
                         "your words are kept below.")
                return
            snapshot = service.canonicals(board_id)
            if sense_id:
                if not snapshot or snapshot.get("state") != "ok":
                    rerender("There are no dictionary definitions to pick. "
                             "Write your own below.", sense="", text=original)
                    return
                wanted = {str(item.get("sense_id"))
                          for item in snapshot.get("senses", [])}
                if sense_id not in wanted:
                    rerender("That definition is not in this Symposium. "
                             "Pick one below.", sense="", text=original)
                    return
            elif original:
                pass
            else:
                rerender("Pick a definition or write your own.")
                return
            # Every refusal check happens before the first mutation, so a
            # refused claim leaves the counts exactly as they were.
            try:
                if service.state(board_id).status == "closed":
                    rerender("This Symposium is closed. "
                             "No new definitions can be claimed.")
                    return
                if service.state(board_id).active_node_id is not None:
                    rerender("This Symposium already has an active "
                             "definition. Talk about it together.",
                             sense="", text="")
                    return
                # The claim carries the participant's stored identity: the
                # board handle decides who the board records, and the stored
                # name is only the fallback for records that predate
                # handles. The page renderer (a placeholder when
                # Anonymous Mode is on)
                # must never decide it, so it is not called here.
                if sense_id:
                    service.claim_canonical(
                        board_id, sense_id,
                        claimant_display=person.get("name"),
                        handle_id=person.get("handle_id"))
                else:
                    service.claim_original(
                        board_id, original,
                        claimant_display=person.get("name"),
                        handle_id=person.get("handle_id"))
            except Exception:
                rerender("That claim could not be recorded. "
                         "Please try again.")
                return
            self._redirect(_symposium_url(record["board_id"],
                                          person["token"]))

        # -- writes -----------------------------------------------------
        def _send(self, status: int, payload: bytes,
                  content_type: str = "text/html; charset=utf-8"):
            body = bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _set_cookie(self, token: str):
            self._cookie = token

        def _redirect(self, location: str):
            self.send_response(303)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            if getattr(self, "_cookie", None):
                self.send_header(
                    "Set-Cookie",
                    f"{COOKIE_NAME}={self._cookie}; Path=/; "
                    f"Max-Age={COOKIE_MAX_AGE}")
            self.end_headers()

    return ForumHandler


def run(service, *, host: str = "127.0.0.1", port: int = 8000):
    """Serve one ``BoardService`` forever (blocking)."""
    server = ThreadingHTTPServer((host, port), make_handler(service))
    print(f"Forum serving at http://{host}:{server.server_port}/",
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return server


def main(argv=None) -> int:
    """One command starts the forum on the host Mac: ``python -m web.forum``.

    Serves the repo-local ``store/`` data home with the live dictionary
    chain (zero keys: Wiktionary first, Free Dictionary second).
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--store", default="store")
    args = parser.parse_args(argv)
    from server.service import BoardService
    service = BoardService(Path(args.store))
    run(service, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
