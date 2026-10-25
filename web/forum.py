"""Forum web server: start a Symposium with its people and define its word.

Stdlib only: ``http.server`` request handling, plain server-rendered pages
and forms, no dependencies, and only a thumbnail of JavaScript (each
invitation row's Copy button). One command starts it on the host Mac::

    python -m web.forum

On screen it is always a Symposium, never anything else. The host starts
one from the start page with their own name and email, the word and the
other participants (a name and an email each).
A Symposium is its word plus its people: the same word with the same people
has only one open Symposium at a time, and the same word with different
people is a new one. It opens for talk at once; there is no Begin button.

After starting, the host sees an invitation page listing each person's
personal link with a copy button. A link carries no protection: opening it
signs that browser in as that person, with no password. The first visit
shows a short welcome page (the word, who else is in it, three sentences on
how it works, a button to go in). Only the host ever sees emails; everyone
else sees names.

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
same form with a plain-words notice and the person's inputs kept, never an
error page. Visible pages never show emails except to the host, machine ids
(node, question or handle ids, sense ids, underscore names), or controls
that exist only for testing. Sense ids travel only inside form values.
"""

from __future__ import annotations

import argparse
import html
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dictionary.normalize import normalize_x
from server.model import now_iso as _now
from server.symposium import (
    SymposiumStore,
    normalize_email,
    parse_guest_lines,
    people_key,
    valid_email,
)

COOKIE_NAME = "sdf_token"


def _notice_html(notice: str | None) -> str:
    if not notice:
        return ""
    return f"<p class=\"notice\">{html.escape(notice)}</p>\n"


def _page(title: str, body: str) -> bytes:
    return ("<!DOCTYPE html>\n<html lang=\"en\">\n<head>"
            "<meta charset=\"utf-8\">\n"
            f"<title>{html.escape(title)}</title></head>\n<body>\n"
            f"{body}\n</body>\n</html>\n").encode("utf-8")


def _start_page(store: SymposiumStore, notice: str | None = None, *,
                host_name: str = "", host_email: str = "", word: str = "",
                guests: str = "") -> bytes:
    rows = []
    for record in store.all_records():
        names = ", ".join(html.escape(p["name"])
                          for p in record["participants"])
        rows.append(f"<li>{html.escape(record['title'])} — {names}</li>")
    listing = ("<ul>\n" + "\n".join(rows) + "\n</ul>" if rows
               else "<p>No symposiums yet — start the first one above.</p>")
    body = (
        "<h1>Socratic Dialogue Forum</h1>\n"
        "<p>Start a Symposium with its people, then talk its word through.</p>\n"
        + _notice_html(notice) +
        "<h2>Start a Symposium</h2>\n"
        "<form method=\"post\" action=\"/start\">\n"
        "<p><label>Your name (the host): "
        "<input type=\"text\" name=\"host_name\" "
        f"value=\"{html.escape(host_name, quote=True)}\"></label></p>\n"
        "<p><label>Your email (the host): "
        "<input type=\"text\" name=\"host_email\" "
        f"value=\"{html.escape(host_email, quote=True)}\"></label></p>\n"
        "<p><label>The word: "
        "<input type=\"text\" name=\"word\" "
        f"value=\"{html.escape(word, quote=True)}\"></label></p>\n"
        "<p><label>The other people, one per line as "
        "Name &lt;email&gt;:<br>"
        "<textarea name=\"guests\" rows=\"4\" cols=\"50\" "
        "placeholder=\"Bohdan &lt;name@example.com&gt;\">"
        f"{html.escape(guests)}</textarea></label></p>\n"
        "<p><button type=\"submit\">Start the Symposium</button></p>\n"
        "</form>\n"
        "<h2>Symposiums</h2>\n" + listing)
    return _page("Socratic Dialogue Forum", body)


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
    parts = ["<h2>Definitions from the dictionaries</h2>", "<ol>"]
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
        return ("<h2>Active definition</h2>\n"
                "<p>No active definition yet — "
                "pick or write the first one below.</p>")
    provenances = service.provenance_map(record["board_id"])
    parts = ["<h2>Active definition</h2>", "<ol>"]
    for node in nodes:
        provenance = provenances.get(node.node_id, {})
        handle_id = provenance.get("claimed_by", node.defender)
        holder = state.handles.get(handle_id)
        name = holder.display if holder is not None else "unknown"
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


def _claim_form(record: dict, person: dict, snapshot: dict | None,
                sense: str = "", original: str = "") -> str:
    action = ("/symposiums/" + urllib.parse.quote(record["board_id"], safe="")
              + "/claim")
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
    return (
        "<h2>Claim the definition</h2>\n"
        f"<p>Claiming as {html.escape(person['name'])}.</p>\n"
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
    others = [p["name"] for p in record["participants"]
              if p["token"] != person["token"]]
    company = (" with " + ", ".join(html.escape(n) for n in others)
               if others else "")
    inv_url = ("/symposiums/" + urllib.parse.quote(record["board_id"], safe="")
               + "/invitations?token=" + urllib.parse.quote(
                   next(p["token"] for p in record["participants"]
                        if p["is_host"]), safe=""))
    body = (
        f"<h1>{html.escape(record['title'])}</h1>\n"
        f"<p>A Symposium on {html.escape(record['word'])}{company}.</p>\n"
        + _notice_html(notice)
        + _definitions_section(snapshot)
        + _attempts_section(service, record)
        + claim
        + f"<p><a href=\"{inv_url}\">Invitation links</a> "
          "(the host's page).</p>\n")
    return _page(f"{record['title']} — Symposium", body)


def _invitations_page(record: dict, notice: str | None = None) -> bytes:
    rows = []
    for person in record["participants"]:
        link = "/join/" + person["token"]
        rows.append(
            f"<li><span class=\"who\">{html.escape(person['name'])}</span> "
            f"&lt;{html.escape(person['email'])}&gt;<br>"
            f"<input type=\"text\" readonly value=\"{html.escape(link, quote=True)}\" size=\"40\"> "
            "<button type=\"button\" "
            "onclick=\"navigator.clipboard.writeText("
            "this.parentElement.querySelector('input').value)\">"
            "Copy</button> "
            f"<a href=\"{html.escape(link, quote=True)}\">Open</a></li>")
    in_url = ("/symposiums/" + urllib.parse.quote(record["board_id"], safe="")
              + "?token=" + urllib.parse.quote(
                  next(p["token"] for p in record["participants"]
                       if p["is_host"]), safe=""))
    body = (
        f"<h1>{html.escape(record['title'])}</h1>\n"
        "<p>Each person opens their own link below. "
        "A link signs that browser in as that person, with no password — "
        "until invitation emails arrive, copy each link to its person.</p>\n"
        + _notice_html(notice)
        + "<ul>\n" + "\n".join(rows) + "\n</ul>\n"
        f"<p><a href=\"{in_url}\">Go to the Symposium</a></p>\n")
    return _page(f"{record['title']} — invitations", body)


def _welcome_page(record: dict, person: dict) -> bytes:
    others = [html.escape(p["name"]) for p in record["participants"]
              if p["token"] != person["token"]]
    action = "/join/" + person["token"] + "/enter"
    body = (
        f"<h1>{html.escape(record['word'])}</h1>\n"
        f"<p>Welcome, {html.escape(person['name'])}.</p>\n"
        "<p>You are joining a Symposium on "
        f"{html.escape(record['word'])}"
        + (" with " + ", ".join(others) + "." if others
           else ", just you for now.") + "</p>\n"
        "<p>How it works: you define one word together, "
        "one definition at a time.</p>\n"
        "<p>Anyone can challenge the active definition "
        "with a counterexample.</p>\n"
        "<p>The Symposium votes on each challenge, "
        "and the majority carries it.</p>\n"
        f"<form method=\"post\" action=\"{action}\">\n"
        "<p><button type=\"submit\">Go in</button></p>\n"
        "</form>")
    return _page(f"{record['word']} — welcome", body)


def _token_from(query: dict, headers) -> str:
    values = query.get("token", [])
    if values:
        return values[0]
    cookie = headers.get("Cookie", "") if headers is not None else ""
    for chunk in str(cookie).split(";"):
        name, _, value = chunk.partition("=")
        if name.strip() == COOKIE_NAME:
            return value.strip()
    return ""


def make_handler(service):
    """Build a stdlib request-handler class bound to one ``BoardService``."""
    store = SymposiumStore(service.root)

    def _symposium_url(record: dict, person: dict) -> str:
        return ("/symposiums/" + urllib.parse.quote(record["board_id"], safe="")
                + "?token=" + urllib.parse.quote(person["token"], safe=""))

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
                    store,
                    "That page is not available right now. Start here."))

        def _routed_get(self):
            parts = urllib.parse.urlsplit(self.path)
            path = parts.path
            query = urllib.parse.parse_qs(parts.query)
            if path == "/":
                self._send(200, _start_page(store))
                return
            segs = path.strip("/").split("/")
            if len(segs) == 2 and segs[0] == "join":
                self._handle_join(urllib.parse.unquote(segs[1]))
                return
            if (len(segs) == 3 and segs[0] == "symposiums"
                    and segs[2] == "invitations"):
                self._handle_invitations(urllib.parse.unquote(segs[1]),
                                         query)
                return
            if len(segs) == 2 and segs[0] == "symposiums":
                self._handle_symposium(urllib.parse.unquote(segs[1]), query)
                return
            self._send(200, _start_page(
                store, "That page does not exist. Start here."))

        def do_POST(self):
            try:
                self._routed_post()
            except Exception:
                self._send(200, _start_page(
                    store,
                    "That request could not be completed. Start here."))

        def _routed_post(self):
            parts = urllib.parse.urlsplit(self.path)
            path = parts.path
            length = self.headers.get("Content-Length")
            try:
                size = int(length) if length is not None else 0
            except ValueError:
                size = 0
            raw = self.rfile.read(size) if size > 0 else b""
            fields = urllib.parse.parse_qs(raw.decode("utf-8", "replace"))

            def field(name: str) -> str:
                values = fields.get(name, [])
                return values[0] if values else ""

            if path == "/start":
                self._handle_start(field("host_name"), field("host_email"),
                                   field("word"), field("guests"))
                return
            segs = path.strip("/").split("/")
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
            self._send(200, _start_page(
                store, "That page does not exist. Start here."))

        # -- the start form -------------------------------------------
        def _handle_start(self, host_name: str, host_email: str, word: str,
                          guests: str):
            host_name, host_email = host_name.strip(), host_email.strip()
            word = word.strip()

            def rerender(notice: str) -> None:
                self._send(200, _start_page(
                    store, notice, host_name=host_name,
                    host_email=host_email, word=word, guests=guests))

            if not host_name:
                rerender("Please type your name first, so people know "
                         "who invited them.")
                return
            if not valid_email(host_email):
                rerender("Please type your email as name@example.com, "
                         "so your invitation link knows you.")
                return
            if not word or not normalize_x(word):
                rerender("Please type the word this Symposium will define.")
                return
            try:
                guest_pairs = parse_guest_lines(guests)
            except ValueError as exc:
                rerender(str(exc))
                return
            people = ([{"name": host_name, "email": host_email,
                        "is_host": True}]
                      + [{"name": name, "email": email, "is_host": False}
                         for name, email in guest_pairs])
            emails = [normalize_email(p["email"]) for p in people]
            if len(set(emails)) != len(emails):
                rerender("Two people share one email. "
                         "Each person needs their own email.")
                return
            names = [p["name"].strip().lower() for p in people]
            if len(set(names)) != len(names):
                rerender("Two people share one name. "
                         "Please give each person a different name.")
                return
            key = people_key(emails)
            word_norm = normalize_x(word)
            # A Symposium is its word plus its people: the same word with
            # the same people has only one open Symposium at a time. A
            # closed one frees the word-and-people for a numbered next one.
            for prior in store.lineage(word_norm, key):
                try:
                    if service.state(prior["board_id"]).status == "open":
                        rerender(
                            f"A Symposium on {prior['word']} with these "
                            "people is already open. Ask its host for "
                            "your personal link, or start one with "
                            "different people.")
                        return
                except Exception:
                    continue
            ordinal = len(store.lineage(word_norm, key)) + 1
            try:
                opened = service.open_board(word, None)
            except Exception:
                rerender("That Symposium could not be opened. "
                         "Please try again.")
                return
            board_id = opened.board_id
            try:
                machine = service.machine(board_id)
                for person in people:
                    machine.enroll_handle(person["name"])
            except Exception:
                rerender("That Symposium could not gather its people. "
                         "Please try again.")
                return
            record = store.create(
                board_id=board_id, word=word, people=people,
                ordinal=ordinal, created_at=_now())
            host_token = next(p["token"] for p in record["participants"]
                              if p["is_host"])
            self._redirect(
                "/symposiums/" + urllib.parse.quote(board_id, safe="")
                + "/invitations?token=" + urllib.parse.quote(host_token,
                                                             safe=""))

        # -- invitations, welcome, entering -----------------------------
        def _handle_invitations(self, board_id: str, query: dict):
            token = _token_from(query, self.headers)
            record = store.get(board_id)
            if record is None:
                self._send(200, _start_page(
                    store, "That Symposium does not exist. Start it below."))
                return
            found = next((p for p in record["participants"]
                          if p["token"] == token), None)
            if found is None:
                self._send(200, _start_page(
                    store, "That invitation link is not recognized. "
                           "Start here, or ask the host for your link."))
                return
            if not found["is_host"]:
                self._redirect(_symposium_url(record, found))
                return
            self._send(200, _invitations_page(record))

        def _handle_join(self, token: str):
            record, person = store.get_by_token(token)
            if record is None or person is None:
                self._send(200, _start_page(
                    store, "That invitation link is not recognized. "
                           "Start here, or ask the host for your link."))
                return
            if person["joined"]:
                self._set_cookie(token)
                self._redirect(_symposium_url(record, person))
                return
            self._set_cookie(token)
            self._send(200, _welcome_page(record, person))

        def _handle_enter(self, token: str):
            record, person = store.get_by_token(token)
            if record is None or person is None:
                self._send(200, _start_page(
                    store, "That invitation link is not recognized. "
                           "Start here, or ask the host for your link."))
                return
            store.mark_joined(record["board_id"], token)
            self._set_cookie(token)
            self._redirect(_symposium_url(record, person))

        # -- the Symposium page and its first claim ----------------------
        def _handle_symposium(self, board_id: str, query: dict):
            token = _token_from(query, self.headers)
            record = store.get(board_id)
            if record is None:
                self._send(200, _start_page(
                    store, "That Symposium does not exist. Start it below."))
                return
            person = next((p for p in record["participants"]
                           if p["token"] == token), None)
            if person is None:
                other, _ = store.get_by_token(token)
                if other is not None:
                    self._redirect(_symposium_url(other, next(
                        p for p in other["participants"]
                        if p["token"] == token)))
                    return
                self._send(200, _start_page(
                    store, "That invitation link is not recognized. "
                           "Start here, or ask the host for your link."))
                return
            if not person["joined"]:
                self._send(200, _welcome_page(record, person))
                return
            self._send(200, _symposium_page(service, record, person))

        def _handle_claim(self, board_id: str, token: str, sense_id: str,
                          original: str):
            record = store.get(board_id)
            if record is None:
                self._send(200, _start_page(
                    store, "That Symposium does not exist. Start it below."))
                return
            person = next((p for p in record["participants"]
                           if p["token"] == token), None)
            if person is None:
                self._send(200, _start_page(
                    store, "That invitation link is not recognized. "
                           "Start here, or ask the host for your link."))
                return
            if not person["joined"]:
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
                if sense_id:
                    service.claim_canonical(
                        board_id, sense_id,
                        claimant_display=person["name"])
                else:
                    service.claim_original(
                        board_id, original,
                        claimant_display=person["name"])
            except Exception:
                rerender("That claim could not be recorded. "
                         "Please try again.")
                return
            self._redirect(_symposium_url(record, person))

        # -- writes -----------------------------------------------------
        def _send(self, status: int, payload: bytes):
            body = bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
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
                    f"{COOKIE_NAME}={self._cookie}; Path=/")
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
