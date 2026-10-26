"""Symposium records: one dialogue is its word plus its participants.

Stdlib only. A Symposium is the user-facing name for one dialogue; the
verdict state underneath stays a board (see :mod:`server.service`), and no
page in :mod:`web.forum` ever shows that word on screen. Every Start makes
a new Symposium: the old rule of one open Symposium per word and group was
dropped once emails stopped being entered by the host (Human, 2026-10-24),
and the next Symposium on the same word with the same host is numbered
("Justice, second symposium").

The invitation link is identity here: each participant carries a personal
token, and opening that token's link signs the browser in as that
participant with no password. Nobody ever sees another participant's email,
the host included; no page shows anyone's email but the host's own on the
host's own players page.

The record holds the Symposium's name (typed by the host in Settings) and
Anonymous Mode (off by default), alongside the word and one row per
participant: their token, the host's note to the invitee, joined or not,
and once joined their name (Anonymous Mode off).

Durability mirrors the registry: one small JSON file under the service's
data root, rewritten atomically.
"""

from __future__ import annotations

import json
import re
import secrets
from pathlib import Path
from typing import Any

from dictionary.normalize import normalize_x
from server.store import atomic_write_json

SYMPOSIUMS_FILENAME = "symposiums.json"
SYMPOSIUMS_VERSION = 1

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(email: str) -> str:
    """Canonical email identity: stripped and lowercased."""
    return str(email).strip().lower()


def valid_email(email: str) -> bool:
    """A plain-shape check: something, an @, something, a dot, something."""
    return bool(_EMAIL_RE.match(str(email).strip()))


def host_key(email: str) -> list[str]:
    """Identity for one Symposium's host: their email alone.

    Only the host's email goes in (guests never give theirs to the host),
    so the lineage of numbered Symposiums ("Justice, second symposium")
    is keyed by the host alone."""
    return [normalize_email(email)]


_ORDINAL_WORDS = {
    2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth",
    7: "seventh", 8: "eighth", 9: "ninth", 10: "tenth",
}


def ordinal_word(n: int) -> str:
    """``2 -> "second"``; past ten, ``11 -> "11th"``."""
    if n in _ORDINAL_WORDS:
        return _ORDINAL_WORDS[n]
    if 10 <= (n % 100) <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _new_participant(*, is_host: bool = False, joined: bool = False,
                     handle_id: str | None = None) -> dict[str, Any]:
    """One participant: token, joined flag, note, host flag."""
    participant: dict[str, Any] = {
        "is_host": bool(is_host),
        "token": secrets.token_urlsafe(18),
        "joined": bool(joined),
        "note": "",
    }
    if handle_id is not None:
        participant["handle_id"] = handle_id
    return participant


class SymposiumStore:
    """``board_id -> Symposium`` map with an atomic single-file rewrite.

    The on-disk shape is exactly ``{"version", "symposiums"}``; tokens are
    minted here (never derived from emails) and ``joined`` tracks who has
    opened their welcome page.
    """

    def __init__(self, root: Path | str):
        self.path = Path(root) / SYMPOSIUMS_FILENAME
        self.records: dict[str, dict[str, Any]] = {}
        self.load()

    # -- reads --------------------------------------------------------

    def get(self, board_id: str) -> dict[str, Any] | None:
        return self.records.get(board_id)

    def get_by_token(self, token: str) -> tuple[dict | None, dict | None]:
        """The ``(symposium, participant)`` holding ``token``."""
        for record in self.records.values():
            for person in record["participants"]:
                if person["token"] == token:
                    return record, person
        return None, None

    def lineage(self, word_norm: str, key: list[str]) -> list[dict]:
        """Every Symposium with this word and these people, oldest first."""
        rows = [r for r in self.records.values()
                if r["word_norm"] == word_norm
                and r["people_key"] == list(key)]
        return sorted(rows, key=lambda r: r["created_at"])

    def all_records(self) -> list[dict[str, Any]]:
        return sorted(self.records.values(),
                      key=lambda r: r["created_at"])

    # -- writes -------------------------------------------------------

    def create(self, *, board_id: str, word: str, players: list[dict],
               ordinal: int,
               created_at: str,
               symposium_name: str | None = None,
               anonymous: bool = False) -> dict[str, Any]:
        """Persist one Symposium; ``players`` holds name/email/is_host/joined/handle_id maps.

        The host arrives named (their start-screen name and email, joined
        at once, with their board handle); every guest arrives as an
        empty participant made by "Add a player" and names themselves on
        arrival in a later Bead, so a participant holds only a token, a
        joined flag, the board handle and the host's note until
        then. ``anonymous`` is the host's Anonymous Mode switch (off by
        default); the Symposium's name lives in ``name`` alone.

        Concurrency lives one layer up: every write reaches here inside
        the forum's mutation lock (web/forum.py), and each file rewrite
        gets its own tmp file in atomic_write_json (server/store.py)."""
        name = str(symposium_name or "").strip()
        participants = []
        for player in players:
            participant = _new_participant(
                is_host=bool(player.get("is_host")),
                joined=bool(player.get("joined", False)),
                handle_id=player.get("handle_id"))
            if player.get("name") is not None:
                participant["name"] = player["name"]
            if player.get("email") is not None:
                participant["email"] = player["email"]
            participants.append(participant)
        record = {
            "board_id": board_id,
            "word": str(word).strip(),
            "word_norm": normalize_x(word),
            # On-disk field name stays "people_key" for stored records;
            # its value holds the host's email only (see host_key).
            "people_key": host_key(next(
                p["email"] for p in participants if "email" in p)),
            "participants": participants,
            "ordinal": ordinal,
            "name": name,
            "created_at": created_at,
            "anonymous": bool(anonymous),
        }
        self.records[board_id] = record
        self.save()
        return record

    def add_player(self, board_id: str,
                   handle_id: str | None = None) -> dict[str, Any] | None:
        """Make one empty participant: a token, unjoined, no name yet.

        The host taps "Add a player" once per guest; the guest names
        themselves when they open the link. Returns the new participant."""
        record = self.records.get(board_id)
        if record is None:
            return None
        participant = _new_participant(handle_id=handle_id)
        record["participants"].append(participant)
        self.save()
        return participant

    def set_note(self, board_id: str, token: str, note: str) -> dict | None:
        """Keep the host's note to one invitee; return the player saved.

        The note travels to the invitee inside the row's Share message
        (the note, then the player's personal link). Returning the
        participant keeps the lookup in one place: callers never search
        the record again for the note they just saved."""
        record = self.records.get(board_id)
        if record is None:
            return None
        for person in record["participants"]:
            if person["token"] == token:
                person["note"] = str(note).strip()[:200]
                self.save()
                return person
        return None

    def mark_joined(self, board_id: str, token: str) -> dict | None:
        """Record one participant's first visit through their welcome page."""
        record = self.records.get(board_id)
        if record is None:
            return None
        for person in record["participants"]:
            if person["token"] == token:
                person["joined"] = True
                self.save()
                return record
        return None

    def save(self) -> None:
        """Atomically rewrite the Symposium records via the shared helper."""
        payload = {"version": SYMPOSIUMS_VERSION,
                   "symposiums": self.records}
        atomic_write_json(self.path, payload)

    def load(self) -> None:
        self.records = {}
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            rows = payload["symposiums"]
            if not isinstance(rows, dict):
                raise TypeError("symposiums must be a mapping")
            self.records = dict(rows)
        except (ValueError, TypeError, KeyError, OSError):
            self.records = {}


__all__ = [
    "SYMPOSIUMS_FILENAME", "SYMPOSIUMS_VERSION",
    "normalize_email", "valid_email", "host_key",
    "ordinal_word",
    "SymposiumStore",
]
