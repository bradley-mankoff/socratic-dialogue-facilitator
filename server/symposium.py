"""Symposium records: one dialogue is its word plus its people.

Stdlib only. A Symposium is the user-facing name for one dialogue; the
verdict state underneath stays a board (see :mod:`server.service`), and no
page in :mod:`web.forum` ever shows that word on screen. Identity is the
normalized word plus the normalized email set: the same word with the same
people has at most one open Symposium at a time, the same word with
different people is a new one, and after one closes the next with the same
word and people is numbered ("Justice, second symposium").

Email is identity here: each participant carries a personal token, and
opening that token's link signs the browser in as that participant with no
password. Only the host ever sees emails; every other page shows names.

Durability mirrors the registry: one small JSON file under the service's
data root, rewritten atomically.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from pathlib import Path
from typing import Any

from dictionary.normalize import normalize_x

SYMPOSIUMS_FILENAME = "symposiums.json"
SYMPOSIUMS_VERSION = 1

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(email: str) -> str:
    """Canonical email identity: stripped and lowercased."""
    return str(email).strip().lower()


def valid_email(email: str) -> bool:
    """A plain-shape check: something, an @, something, a dot, something."""
    return bool(_EMAIL_RE.match(str(email).strip()))


def people_key(emails: list[str]) -> list[str]:
    """Order-free identity for one Symposium's people: sorted emails."""
    return sorted({normalize_email(email) for email in emails})


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


def symposium_title(word: str, ordinal: int) -> str:
    """Display name: the word, then the numbered-symposium phrase."""
    word = str(word).strip()
    if ordinal <= 1:
        return word
    return f"{word}, {ordinal_word(ordinal)} symposium"


def parse_guest_lines(text: str) -> list[tuple[str, str]]:
    """Parse the other-participants box: one person per line.

    Each line is ``Name <email>`` or ``Name, email`` (a bare trailing
    ``Name email`` also reads). Blank lines are skipped. Raises
    :class:`ValueError` with a plain-words message naming the bad line.
    """
    guests: list[tuple[str, str]] = []
    for lineno, raw in enumerate(str(text).splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if "<" in line and ">" in line:
            name, _, rest = line.partition("<")
            email = rest.partition(">")[0]
        elif "," in line:
            name, _, email = line.rpartition(",")
        else:
            parts = line.split()
            if len(parts) < 2:
                raise ValueError(
                    f"line {lineno} needs a name and an email, "
                    f"like 'Bohdan <bohdan@example.com>'")
            name, email = " ".join(parts[:-1]), parts[-1]
        name, email = name.strip(), email.strip()
        if not name:
            raise ValueError(
                f"line {lineno} needs a name before the email")
        if not valid_email(email):
            raise ValueError(
                f"line {lineno} has an email that does not read "
                f"like name@example.com")
        guests.append((name, email))
    return guests


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

    def create(self, *, board_id: str, word: str, people: list[dict],
               ordinal: int,
               created_at: str) -> dict[str, Any]:
        """Persist one Symposium; ``people`` holds name/email/is_host maps."""
        participants = [{
            "name": person["name"],
            "email": person["email"],
            "is_host": bool(person.get("is_host")),
            "token": secrets.token_urlsafe(18),
            "joined": False,
        } for person in people]
        record = {
            "board_id": board_id,
            "word": str(word).strip(),
            "word_norm": normalize_x(word),
            "people_key": people_key([p["email"] for p in participants]),
            "participants": participants,
            "ordinal": ordinal,
            "title": symposium_title(word, ordinal),
            "created_at": created_at,
        }
        self.records[board_id] = record
        self.save()
        return record

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
        payload = {"version": SYMPOSIUMS_VERSION,
                   "symposiums": self.records}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)

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
    "normalize_email", "valid_email", "people_key",
    "ordinal_word", "symposium_title", "parse_guest_lines",
    "SymposiumStore",
]
