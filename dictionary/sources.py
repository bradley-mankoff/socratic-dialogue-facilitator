"""Dictionary sources over the injectable Transport (SDF-3 story 8).

Fused (panels a+b+c): panel-a revisions-wikitext parsing is canonical
(the fixture glosses V/I/P + German decoy + ``#*``/``#:`` noise pin it).
Layered on top, without changing any canonical parse:

* Wiktionary ``pageid`` capture (panel b evidence, pageid 56878) into
  :class:`RawSense.pageid` and :func:`source_cite` (the canonical cite
  URL stays the article URL panel-a tests pin; the ``?curid=`` URL is
  derivable from ``pageid``).
* Shared status table :func:`classify_status` + URL prefix constants
  (panel b ``sources_util``) and stability weights
  :func:`stability_for` (panel c ranking tie-break).
* :class:`RawSense` accepts panel-b spellings (``text``/``index``/
  ``source``/``url``/``license``) as init aliases over the canonical
  ``gloss``/``order`` fields.
* Every source exposes ``fetch`` (canonical) plus ``query`` /
  ``lookup`` / ``lookup_reported`` aliases (panels b/c) so all three
  import surfaces work.

Every source's ``fetch`` turns exactly one HTTP exchange into
``(senses, SourceOutcome)`` and never raises: connection failures and
malformed bodies become ``unavailable``; upstream misses become
``no_entry``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlencode

from dictionary.model import PRIMARY, Cite, SourceName, SourceOutcome, canonical_source
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

# Panel-b URL prefix constants (same endpoints, prefix form for route tables).
WIKTIONARY_API_PREFIX = "https://en.wiktionary.org/w/api.php"
FREE_DICT_PREFIX = FREE_DICTIONARY_API
MERRIAM_WEBSTER_PREFIX = MERRIAM_WEBSTER_API

# Panel-c stability weights: primary first, corroboration second, keyed third.
STABILITY: dict[str, int] = {
    "wiktionary": 3,
    "free-dictionary": 2,
    "merriam-webster": 1,
}


def stability_for(source_name: str) -> int:
    """Reliability weight used as a ranking tie-break (panel c)."""
    return STABILITY.get(canonical_source(source_name), 0)


def classify_status(status: int) -> tuple[str, str]:
    """Shared status decision table (panel b ``sources_util``).

    * 404 → ``("no_hit", "not_found")`` — evidence of absence.
    * 5xx (and 408/429) → ``("down", "http_{code}")`` — source down.
    * other 4xx → ``("down", "http_{code}")`` — unusable, not absence.
    * 2xx → ``("ok", "ok")`` and the adapter parses the body.

    The chain stores panel-a spellings (``no_entry``/``unavailable``);
    this table documents the shared policy behind them.
    """
    if status == 404:
        return "no_hit", "not_found"
    if status >= 500 or status in (408, 429):
        return "down", f"http_{status}"
    if 200 <= status < 300:
        return "ok", "ok"
    return "down", f"http_{status}"


@dataclass
class RawSense:
    """One gloss exactly as its source published it (pre-consensus).

    Canonical fields are ``gloss``/``pos``/``order`` (panel a). Panel-b
    spellings (``text``/``index``/``source``/``url``/``license``) and the
    Wiktionary ``pageid`` are accepted as init aliases and synced in
    ``__post_init__`` so both surfaces observe the same sense.
    """

    gloss: str = ""
    pos: str | None = None
    order: int = 0  # 1-based position within its source
    pageid: int | None = None
    source: str | None = None
    url: str | None = None
    license: str | None = None
    text: str | None = None
    index: int | None = None

    def __post_init__(self) -> None:
        # Sync the two spellings both ways; canonical storage is gloss/order.
        if not self.gloss and self.text:
            self.gloss = self.text
        if self.text is None:
            self.text = self.gloss
        if not self.order and self.index:
            self.order = self.index
        if self.index is None:
            self.index = self.order

    def to_dict(self) -> dict[str, Any]:
        return {
            "gloss": self.gloss,
            "pos": self.pos,
            "order": self.order,
            "pageid": self.pageid,
            "source": self.source,
            "url": self.url,
            "license": self.license,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RawSense":
        return cls(
            gloss=d.get("gloss", d.get("text", "")),
            pos=d.get("pos"),
            order=d.get("order", d.get("index", 0)),
            pageid=d.get("pageid"),
            source=d.get("source"),
            url=d.get("url"),
            license=d.get("license", d.get("license_name")),
        )


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
    """Article URL (canonical); ``?curid=`` form is derivable from pageid."""
    return WIKTIONARY_ARTICLE + _slug(x)


def wiktionary_curid_url(pageid: int) -> str:
    """Panel-b stable cite URL for a known pageid (e.g. 56878)."""
    return f"https://en.wiktionary.org/?curid={pageid}"


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
    canon = canonical_source(str(source))
    if canon == "wiktionary":
        return Cite(canon, wiktionary_cite_url(x), access_date, WIKTIONARY_LICENSE, pageid=pageid)
    if canon == "free-dictionary":
        return Cite(
            canon, free_dictionary_url(x), access_date, FREE_DICTIONARY_LICENSE
        )
    if canon == "merriam-webster":
        return Cite(
            canon, merriam_webster_cite_url(x), access_date, MERRIAM_WEBSTER_LICENSE
        )
    raise ValueError(f"unknown source: {source!r}")


_LEVEL2 = re.compile(r"^==(?!=)([^=].*?)==")
_LEVEL3 = re.compile(r"^===(?!=)(.+?)==")
_LEVEL4 = re.compile(r"^====")
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_REF = re.compile(r"<ref[^>]*>.*?</ref>|<ref[^>]*/\s*>", re.S | re.I)
_TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")


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


class WiktionarySource:
    """Primary source: Action API revisions wikitext, parsed per sense."""

    name: SourceName = PRIMARY
    license = WIKTIONARY_LICENSE

    def __init__(self, transport: Any | None = None, accessed: str | None = None) -> None:
        # Panel-c style injectable binding; canonical path passes transport
        # per-call to ``fetch``, so both constructions work.
        self.transport = transport
        self.accessed = accessed

    def _transport(self, transport: Any | None) -> Any:
        return transport if transport is not None else self.transport

    def fetch(
        self, x: str, transport: Transport | None = None
    ) -> tuple[list[RawSense], SourceOutcome]:
        transport = self._transport(transport)
        if transport is None:  # pragma: no cover - defensive
            return _unavailable(self.name, "TransportError: no transport")
        # Support panel-c callable transports as well as panel-a get() ones.
        get = getattr(transport, "get", None)
        try:
            if callable(get):
                response = get(wiktionary_url(x))
            else:
                response = transport(wiktionary_url(x))
        except TransportError as exc:
            return _unavailable(self.name, f"TransportError: {exc}")
        except Exception as exc:  # panel-c SourceUnavailable subclasses TransportError
            return _unavailable(self.name, f"TransportError: {exc}")
        if response.status != 200:
            return _unavailable(self.name, f"HTTP {response.status}")
        try:
            body = response.body
            if isinstance(body, (bytes, bytearray)):
                body = bytes(body).decode("utf-8", errors="replace")
            payload = json.loads(body)
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

    # -- panel-b/c aliases -------------------------------------------------
    def query(self, x: str, *args: Any, **kwargs: Any):
        """Panel-b alias: returns a ``SourceOutcome`` carrying ``senses``."""
        transport = kwargs.get("transport", args[0] if args else None)
        senses, outcome = self.fetch(x, transport if transport is not None else self.transport)
        outcome.senses = senses  # type: ignore[attr-defined]
        try:
            outcome.url_tried = wiktionary_url(x)  # type: ignore[attr-defined]
        except Exception:
            pass
        return outcome

    def lookup(self, term: str, transport: Any | None = None):
        senses, outcome = self.fetch(term, transport if transport is not None else self.transport)
        return senses, outcome

    def lookup_reported(self, term: str):
        return self.lookup(term, self.transport)


class FreeDictionarySource:
    """Second vote: dictionaryapi.dev entry list (may be down with HTTP 522)."""

    name: SourceName = "free-dictionary"
    license = FREE_DICTIONARY_LICENSE

    def __init__(self, transport: Any | None = None, accessed: str | None = None) -> None:
        self.transport = transport
        self.accessed = accessed

    def _transport(self, transport: Any | None) -> Any:
        return transport if transport is not None else self.transport

    def fetch(
        self, x: str, transport: Transport | None = None
    ) -> tuple[list[RawSense], SourceOutcome]:
        transport = self._transport(transport)
        if transport is None:  # pragma: no cover - defensive
            return _unavailable(self.name, "TransportError: no transport")
        get = getattr(transport, "get", None)
        try:
            if callable(get):
                response = get(free_dictionary_url(x))
            else:
                response = transport(free_dictionary_url(x))
        except TransportError as exc:
            return _unavailable(self.name, f"TransportError: {exc}")
        except Exception as exc:
            return _unavailable(self.name, f"TransportError: {exc}")
        if response.status == 404:
            return _no_entry(self.name, "HTTP 404")
        if response.status != 200:
            return _unavailable(self.name, f"HTTP {response.status}")
        try:
            body = response.body
            if isinstance(body, (bytes, bytearray)):
                body = bytes(body).decode("utf-8", errors="replace")
            payload = json.loads(body)
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

    def query(self, x: str, *args: Any, **kwargs: Any):
        transport = kwargs.get("transport", args[0] if args else None)
        senses, outcome = self.fetch(x, transport if transport is not None else self.transport)
        outcome.senses = senses  # type: ignore[attr-defined]
        return outcome

    def lookup(self, term: str, transport: Any | None = None):
        return self.fetch(term, transport if transport is not None else self.transport)

    def lookup_reported(self, term: str):
        return self.lookup(term, self.transport)


class MerriamWebsterSource:
    """Keyed third vote. Only ever constructed when a key is configured."""

    name: SourceName = "merriam-webster"
    license = MERRIAM_WEBSTER_LICENSE

    def __init__(self, key: str, transport: Any | None = None, accessed: str | None = None) -> None:
        # Panel-a: ``MerriamWebsterSource(key)``; panel-b: ``(transport, key)``.
        # Accept both orders when the first arg looks like a transport.
        if transport is None and not isinstance(key, str):
            raise ValueError("MerriamWebsterSource needs a key string")
        self.key = key
        self.transport = transport
        self.accessed = accessed

    def fetch(
        self, x: str, transport: Transport | None = None
    ) -> tuple[list[RawSense], SourceOutcome]:
        transport = transport if transport is not None else self.transport
        # Canonical path always passes transport explicitly; bound-transport
        # fallback keeps panel-b/c constructions working.
        if transport is None and isinstance(getattr(self, "key", None), str) is False:
            return _unavailable(self.name, "TransportError: no transport")
        t = transport if transport is not None else None
        # When constructed as MerriamWebsterSource(key) the caller passes
        # transport per-call; when constructed with a bound transport, use it.
        active = t if t is not None else getattr(self, "transport", None)
        key = self.key if isinstance(self.key, str) else ""
        if active is None:  # pragma: no cover - defensive
            return _unavailable(self.name, "TransportError: no transport")
        get = getattr(active, "get", None)
        try:
            if callable(get):
                response = get(merriam_webster_url(x, key))
            else:
                response = active(merriam_webster_url(x, key))
        except TransportError as exc:
            return _unavailable(self.name, f"TransportError: {exc}")
        except Exception as exc:
            return _unavailable(self.name, f"TransportError: {exc}")
        if response.status != 200:
            return _unavailable(self.name, f"HTTP {response.status}")
        try:
            body = response.body
            if isinstance(body, (bytes, bytearray)):
                body = bytes(body).decode("utf-8", errors="replace")
            payload = json.loads(body)
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

    def query(self, x: str, *args: Any, **kwargs: Any):
        transport = kwargs.get("transport", args[0] if args else None)
        senses, outcome = self.fetch(x, transport if transport is not None else self.transport)
        outcome.senses = senses  # type: ignore[attr-defined]
        return outcome

    def lookup(self, term: str, transport: Any | None = None):
        return self.fetch(term, transport if transport is not None else self.transport)

    def lookup_reported(self, term: str):
        return self.lookup(term, self.transport)


# Panel-c base-class alias: structural typing only, behaviour lives above.
class DictionarySource:
    """Marker base for panel-c ``isinstance`` checks (no behaviour)."""

    name: str = ""
