"""Dictionary sources over the injectable Transport (SDF-3 story 8).

Every source's ``fetch`` turns exactly one HTTP exchange into
``(senses, SourceOutcome)`` and never raises: connection failures and
malformed bodies become ``unavailable``; upstream misses become
``no_entry``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import quote, urlencode

from dictionary.model import PRIMARY, Cite, SourceName, SourceOutcome
from dictionary.transport import Transport, TransportError

WIKTIONARY_API = "https://en.wiktionary.org/w/api.php?"
WIKTIONARY_ARTICLE = "https://en.wiktionary.org/wiki/"
WIKTIONARY_LICENSE = "CC BY-SA 3.0"
FREE_DICTIONARY_API = "https://api.dictionaryapi.dev/api/v2/entries/en/"
FREE_DICTIONARY_LICENSE = "unverified-upstream"
MERRIAM_WEBSTER_API = (
    "https://www.dictionaryapi.com/api/v3/references/collegiate/json/"
)
MERRIAM_WEBSTER_ARTICLE = "https://www.merriam-webster.com/dictionary/"
MERRIAM_WEBSTER_LICENSE = "Merriam-Webster (attribution per publisher terms)"

STABILITY: dict[str, int] = {
    "wiktionary": 3,
    "free-dictionary": 2,
    "merriam-webster": 1,
}


def stability_for(source_name: str) -> int:
    """Reliability weight used as a ranking tie-break."""
    return STABILITY.get(str(source_name), 0)


@dataclass
class RawSense:
    """One gloss exactly as its source published it (pre-consensus)."""

    gloss: str = ""
    pos: str | None = None
    order: int = 0  # 1-based position within its source
    pageid: int | None = None


def _slug(x: str) -> str:
    return x.replace(" ", "_")


def wiktionary_url(x: str) -> str:
    return WIKTIONARY_API + urlencode(
        {
            "action": "query",
            "format": "json",
            "prop": "revisions",
            "rvprop": "content",
            "rvslots": "main",
            "redirects": "1",
            "titles": x,
        }
    )


def wiktionary_cite_url(x: str, pageid: int | None = None) -> str:
    """Article URL (canonical)."""
    return WIKTIONARY_ARTICLE + _slug(x)


def free_dictionary_url(x: str) -> str:
    return FREE_DICTIONARY_API + quote(x)


def merriam_webster_url(x: str, key: str) -> str:
    return MERRIAM_WEBSTER_API + quote(x) + "?key=" + key


def merriam_webster_cite_url(x: str) -> str:
    return MERRIAM_WEBSTER_ARTICLE + _slug(x)


def source_cite(
    source: SourceName, x: str, access_date: str, pageid: int | None = None
) -> Cite:
    """Build a complete Source + URL + date + license record without I/O."""
    if source == "wiktionary":
        return Cite(source, wiktionary_cite_url(x), access_date, WIKTIONARY_LICENSE, pageid=pageid)
    if source == "free-dictionary":
        return Cite(
            source, free_dictionary_url(x), access_date, FREE_DICTIONARY_LICENSE
        )
    if source == "merriam-webster":
        return Cite(
            source, merriam_webster_cite_url(x), access_date, MERRIAM_WEBSTER_LICENSE
        )
    raise ValueError(f"unknown source: {source!r}")


_LEVEL2 = __import__("re").compile(r"^==(?!=)([^=].*?)==")
_LEVEL3 = __import__("re").compile(r"^===(?!=)(.+?)===")
_LEVEL4 = __import__("re").compile(r"^====")
_COMMENT = __import__("re").compile(r"<!--.*?-->", __import__("re").S)
_REF = __import__("re").compile(r"<ref[^>]*>.*?</ref>|<ref[^>]*/\s*>", __import__("re").S | __import__("re").I)
_TEMPLATE = __import__("re").compile(r"\{\{[^{}]*\}\}")


def _english_lines(wikitext: str) -> list[str]:
    """Lines inside the level-2 ``==English==`` section (empty if absent)."""
    lines: list[str] = []
    in_english = False
    for line in wikitext.splitlines():
        stripped = line.strip()
        match = _LEVEL2.match(stripped)
        if match:
            if in_english:
                break  # the next level-2 section ends English
            in_english = match.group(1).strip().lower() == "english"
            continue
        if in_english:
            lines.append(line)
    return lines


def _clean_gloss(text: str) -> str:
    text = _COMMENT.sub(" ", text)
    previous = None
    while previous != text:  # defensive: peel non-nested templates to fixpoint
        previous = text
        text = _TEMPLATE.sub(" ", text)
    text = _REF.sub(" ", text)
    text = _COMMENT.sub(" ", text)
    return " ".join(text.split())


def parse_wikitext_senses(wikitext: str, *, pageid: int | None = None) -> list[RawSense]:
    """Parse per-sense glosses from an English Wiktionary wikitext page.

    Sense lines are exactly ``"# "`` prefixed; ``#*``/``#:``/``##`` and bare
    ``#`` are skipped. The current ``===PoS===`` heading supplies ``pos``;
    level-4+ headings reset it to None.
    """
    senses: list[RawSense] = []
    pos: str | None = None
    for line in _english_lines(wikitext):
        stripped = line.strip()
        if _LEVEL4.match(stripped):
            pos = None
            continue
        match = _LEVEL3.match(stripped)
        if match:
            pos = match.group(1).strip().lower()
            continue
        if not line.startswith("# "):
            continue
        gloss = _clean_gloss(line[2:])
        if not gloss:
            continue
        senses.append(RawSense(gloss=gloss, pos=pos, order=len(senses) + 1, pageid=pageid))
    return senses


def _unavailable(source: SourceName, detail: str) -> tuple[list[RawSense], SourceOutcome]:
    return [], SourceOutcome(source, "unavailable", detail)


def _no_entry(source: SourceName, detail: str | None = None) -> tuple[list[RawSense], SourceOutcome]:
    return [], SourceOutcome(source, "no_entry", detail)


def _get(url: str, transport: Transport):
    """One HTTP exchange over the injectable transport."""
    return transport.get(url)


class WiktionarySource:
    """Primary source: Action API revisions wikitext, parsed per sense."""

    name: SourceName = PRIMARY
    license = WIKTIONARY_LICENSE

    def fetch(
        self, x: str, transport: Transport
    ) -> tuple[list[RawSense], SourceOutcome]:
        try:
            response = _get(wiktionary_url(x), transport)
        except TransportError as exc:
            return _unavailable(self.name, f"TransportError: {exc}")
        except Exception as exc:
            return _unavailable(self.name, f"TransportError: {exc}")
        if response.status != 200:
            return _unavailable(self.name, f"HTTP {response.status}")
        try:
            payload = json.loads(response.body)
            page = next(iter(payload["query"]["pages"].values()))
        except (ValueError, TypeError, KeyError, StopIteration, AttributeError):
            return _unavailable(self.name, "invalid JSON")
        if (
            page.get("missing") is not None
            or page.get("pageid") == -1
            or "revisions" not in page
        ):
            return _no_entry(self.name)
        try:
            wikitext = page["revisions"][0]["slots"]["main"]["*"]
        except (KeyError, IndexError, TypeError):
            return _unavailable(self.name, "invalid JSON")
        raw_pageid = page.get("pageid")
        pageid = raw_pageid if isinstance(raw_pageid, int) and raw_pageid > 0 else None
        senses = parse_wikitext_senses(wikitext, pageid=pageid)
        if not senses:
            return _no_entry(self.name)
        return senses, SourceOutcome(self.name, "ok", None)


class FreeDictionarySource:
    """Second vote: dictionaryapi.dev entry list (may be down with HTTP 522)."""

    name: SourceName = "free-dictionary"
    license = FREE_DICTIONARY_LICENSE

    def fetch(
        self, x: str, transport: Transport
    ) -> tuple[list[RawSense], SourceOutcome]:
        try:
            response = _get(free_dictionary_url(x), transport)
        except TransportError as exc:
            return _unavailable(self.name, f"TransportError: {exc}")
        except Exception as exc:
            return _unavailable(self.name, f"TransportError: {exc}")
        if response.status == 404:
            return _no_entry(self.name, "HTTP 404")
        if response.status != 200:
            return _unavailable(self.name, f"HTTP {response.status}")
        try:
            payload = json.loads(response.body)
        except (ValueError, TypeError):
            return _unavailable(self.name, "invalid JSON")
        if not isinstance(payload, list):
            return _unavailable(self.name, "invalid JSON")
        senses: list[RawSense] = []
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            for meaning in entry.get("meanings") or []:
                if not isinstance(meaning, dict):
                    continue
                pos = meaning.get("partOfSpeech")
                for definition in meaning.get("definitions") or []:
                    if not isinstance(definition, dict):
                        continue
                    gloss = definition.get("definition")
                    if isinstance(gloss, str) and gloss.strip():
                        senses.append(
                            RawSense(gloss=gloss, pos=pos, order=len(senses) + 1)
                        )
        if not senses:
            return _no_entry(self.name)
        return senses, SourceOutcome(self.name, "ok", None)


class MerriamWebsterSource:
    """Keyed third vote. Only ever constructed when a key is configured."""

    name: SourceName = "merriam-webster"
    license = MERRIAM_WEBSTER_LICENSE

    def __init__(self, key: str) -> None:
        if not isinstance(key, str):
            raise ValueError("MerriamWebsterSource needs a key string")
        self.key = key

    def fetch(
        self, x: str, transport: Transport
    ) -> tuple[list[RawSense], SourceOutcome]:
        key = self.key if isinstance(self.key, str) else ""
        try:
            response = _get(merriam_webster_url(x, key), transport)
        except TransportError as exc:
            return _unavailable(self.name, f"TransportError: {exc}")
        except Exception as exc:
            return _unavailable(self.name, f"TransportError: {exc}")
        if response.status != 200:
            return _unavailable(self.name, f"HTTP {response.status}")
        try:
            payload = json.loads(response.body)
        except (ValueError, TypeError):
            return _unavailable(self.name, "invalid JSON")
        if not isinstance(payload, list):
            return _unavailable(self.name, "invalid JSON")
        senses: list[RawSense] = []
        for entry in payload:
            if not isinstance(entry, dict):
                continue  # spelling suggestions arrive as plain strings
            shortdefs = entry.get("shortdef")
            if not isinstance(shortdefs, list):
                continue
            pos = entry.get("fl")
            for gloss in shortdefs:
                if isinstance(gloss, str) and gloss.strip():
                    senses.append(
                        RawSense(gloss=gloss, pos=pos, order=len(senses) + 1)
                    )
        if not senses:
            return _no_entry(self.name)
        return senses, SourceOutcome(self.name, "ok", None)
