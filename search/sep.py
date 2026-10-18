"""SDF-16 SEP path: pure URL shaping and labeled entry makers.

The Stanford Encyclopedia of Philosophy is a **philosopher source**. The
spec admits it only as a labeled on-demand voice — a participant links
out to it, or pastes an excerpt from it — and **never crawled, never
fetched, never unprompted**. Server-side fetching (even to "validate" a
link or extract a quote) would be a crawl of a philosopher source on a
semi-automatic path, so this module is I/O-free **by construction**:

* no ``transport`` / ``provider`` / ``fetch`` parameter exists on any
  function here (pinned by signature introspection);
* nothing imports the ``urllib`` request machinery or any dictionary
  transport (pinned by an import scan);
* the only ``urllib`` use is ``urllib.parse`` (pure string shaping);
* excerpts are stored **verbatim** — no normalization, no re-quoting,
  no truncation beyond the hard size cap.

Host rules (``BadSepSource``): https only (no ``http://`` downgrade),
host exactly ``plato.stanford.edu`` — no suffix tricks
(``plato.stanford.edu.evil.com``), no userinfo smuggling
(``plato.stanford.edu@evil.com``), no other encyclopedia hosts.
"""

from __future__ import annotations

from urllib.parse import quote, urlsplit

from search.errors import BadSepSource
from search.model import (
    EXCERPT_MAX_CHARS,
    SEP_ORIGIN_LINK,
    SEP_ORIGIN_PASTE,
    SEP_SITE,
    SepEntry,
)

SEP_HOST = "plato.stanford.edu"


def sep_entry_url(slug: str) -> str:
    """The canonical entry URL for a SEP slug (pure shaping)."""
    return f"{SEP_SITE}/entries/{str(slug).strip().strip('/')}/"


def sep_search_url(x: str) -> str:
    """The SEP site-search URL for X — a link-out suggestion, never a call."""
    return f"{SEP_SITE}/search/searcher.py?query={quote(str(x).strip())}"


def _require_sep_url(url: str) -> str:
    """Strict SEP-URL check; echoes the stripped URL on success.

    ``urlsplit`` splits scheme/hostport/userinfo, so every evil shape
    above fails the exact-host comparison.
    """
    if not isinstance(url, str) or not url.strip():
        raise BadSepSource("a SEP link needs a non-blank URL")
    candidate = url.strip()
    parts = urlsplit(candidate)
    if parts.scheme != "https":
        raise BadSepSource(
            f"SEP links must be https, not {parts.scheme or '(no scheme)'!r}")
    if (parts.hostname or "") != SEP_HOST:
        raise BadSepSource(
            f"only {SEP_HOST} is admitted as a philosopher source, "
            f"got {parts.hostname!r}")
    return candidate


def _require_speaker(speaker) -> str | None:
    """Verbatim display string or None; anything else refuses."""
    if speaker is None:
        return None
    if not isinstance(speaker, str):
        raise BadSepSource("speaker must be a display string or None")
    return speaker if speaker.strip() else None


def make_sep_link(url: str, *, x: str, citation: str = "",
                  retrieved_at: str) -> SepEntry:
    """Admit a SEP link-out as one labeled philosopher voice."""
    _require_sep_url(url)
    if not (isinstance(x, str) and x.strip()):
        raise BadSepSource("a SEP admission is tied to a non-blank X")
    return SepEntry(
        origin=SEP_ORIGIN_LINK,
        url=url.strip(),
        excerpt=None,
        speaker=None,
        retrieved_at=retrieved_at,
        x=x,
        citation=citation,
    )


def make_sep_paste(excerpt: str, *, x: str, citation: str = "",
                   speaker=None, url: str | None = None,
                   retrieved_at: str) -> SepEntry:
    """Admit a pasted SEP excerpt as one labeled philosopher voice.

    The excerpt is stored **verbatim** (whitespace included), capped at
    :data:`EXCERPT_MAX_CHARS`. An optional ``url`` (when the paster knows
    the source) must itself pass the SEP link check.
    """
    if not (isinstance(excerpt, str) and excerpt.strip()):
        raise BadSepSource("a pasted SEP excerpt must be a non-blank string")
    if len(excerpt) > EXCERPT_MAX_CHARS:
        raise BadSepSource(
            f"excerpt longer than {EXCERPT_MAX_CHARS} chars "
            f"({len(excerpt)}); paste less, or link out instead")
    if not (isinstance(x, str) and x.strip()):
        raise BadSepSource("a SEP admission is tied to a non-blank X")
    checked_url = None
    if url is not None:
        checked_url = _require_sep_url(url)
    return SepEntry(
        origin=SEP_ORIGIN_PASTE,
        url=checked_url,
        excerpt=excerpt,
        speaker=_require_speaker(speaker),
        retrieved_at=retrieved_at,
        x=x,
        citation=citation,
    )


__all__ = [
    "SEP_HOST", "EXCERPT_MAX_CHARS", "SEP_SITE",
    "sep_entry_url", "sep_search_url",
    "make_sep_link", "make_sep_paste",
]
