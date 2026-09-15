"""SDF-16 F9–F12 — the SEP path: labeled link-out or pasted excerpt,
I/O-free by construction (no transport, no fetch, no crawl)."""

from __future__ import annotations

import inspect
import json
import pathlib

import pytest

from search.errors import BadSepSource
from search.model import (
    EXCERPT_MAX_CHARS,
    SEP_KIND,
    SEP_ORIGIN_LINK,
    SEP_ORIGIN_PASTE,
    SEP_SITE,
    SEP_SOURCE_LABEL,
    SepEntry,
)
from search.sep import (
    SEP_HOST,
    make_sep_link,
    make_sep_paste,
    sep_entry_url,
    sep_search_url,
)
from tests.search_stubs import TS

ENTRY_URL = "https://plato.stanford.edu/entries/justice/"

EXCERPT = ("  \"Justice is nothing else than the advantage of the stronger.\" "
           "— Thrasymachus, Republic 338c  ")


# -- F9 link-out labeled as philosopher voice -------------------------------

def test_link_is_labeled_philosopher_one_voice():
    entry = make_sep_link(ENTRY_URL, x="justice", retrieved_at=TS)
    assert entry.origin == SEP_ORIGIN_LINK
    assert entry.url == ENTRY_URL            # echoed verbatim
    assert entry.excerpt is None
    assert entry.kind == SEP_KIND
    assert entry.source == "philosopher-sep"
    assert entry.source_label == SEP_SOURCE_LABEL
    assert entry.canonical is False
    assert entry.x == "justice"
    assert entry.retrieved_at == TS


def test_bare_slug_expands_to_the_sep_entry_url():
    entry = make_sep_link(sep_entry_url("justice"), x="justice",
                          retrieved_at=TS)
    assert entry.url == ENTRY_URL


def test_sep_url_shapers_are_pinned_strings():
    assert sep_entry_url("justice") == ENTRY_URL
    assert sep_search_url("justice") == (
        f"{SEP_SITE}/search/searcher.py?query=justice")
    assert sep_search_url("justice thrasymachus") == (
        f"{SEP_SITE}/search/searcher.py?query=justice%20thrasymachus")


# -- F10 pasted excerpt verbatim ---------------------------------------------

def test_paste_stored_verbatim_with_speaker_preserved():
    entry = make_sep_paste(EXCERPT, x="justice", speaker="Polemarchus",
                           citation="Republic 338c", retrieved_at=TS)
    assert entry.origin == SEP_ORIGIN_PASTE
    assert entry.excerpt == EXCERPT          # verbatim, whitespace intact
    assert entry.url is None
    assert entry.speaker == "Polemarchus"    # display string, never enrolled
    assert entry.citation == "Republic 338c"
    assert entry.kind == SEP_KIND and entry.canonical is False


def test_paste_at_the_size_cap_is_admitted_and_over_is_refused():
    cap = "x" * EXCERPT_MAX_CHARS
    at_cap = make_sep_paste(cap, x="justice", retrieved_at=TS)
    assert len(at_cap.excerpt) == EXCERPT_MAX_CHARS
    with pytest.raises(BadSepSource):
        make_sep_paste(cap + "!", x="justice", retrieved_at=TS)


def test_sep_dataclass_shape_errors_raise_badsep():
    with pytest.raises(BadSepSource):
        SepEntry(origin="crawl", url=None, excerpt=None, speaker=None,
                 retrieved_at=TS)
    with pytest.raises(BadSepSource):
        SepEntry(origin=SEP_ORIGIN_LINK, url="https://plato.stanford.edu/",
                 excerpt="not allowed", speaker=None, retrieved_at=TS)
    with pytest.raises(BadSepSource):
        SepEntry(origin=SEP_ORIGIN_LINK, url=None, excerpt=None,
                 speaker=None, retrieved_at=TS)
    with pytest.raises(BadSepSource):
        SepEntry(origin=SEP_ORIGIN_PASTE, url=None, excerpt=None,
                 speaker=None, retrieved_at=TS)


# -- F11 strict host / scheme rules -------------------------------------------

def test_http_downgrade_refused():
    with pytest.raises(BadSepSource):
        make_sep_link("http://plato.stanford.edu/entries/justice/",
                      x="justice", retrieved_at=TS)


def test_evil_hosts_and_suffix_tricks_refused():
    for evil in (
        "https://evil.com/plato.stanford.edu/entries/justice/",
        "https://notplato.stanford.edu/entries/justice/",
        "https://plato.stanford.edu.evil.com/entries/justice/",
        "https://plato.stanford.edu@evil.com/entries/justice/",
        "https://iep.utm.edu/thrasymachus/",       # another encyclopedia host
        "https://example.org/quote",               # not SEP at all
    ):
        with pytest.raises(BadSepSource):
            make_sep_link(evil, x="justice", retrieved_at=TS)
        with pytest.raises(BadSepSource):
            make_sep_paste("quote", x="justice", url=evil, retrieved_at=TS)


def test_blank_url_and_blank_x_refused():
    for bad_url in ("", "   ", None):
        with pytest.raises(BadSepSource):
            make_sep_link(bad_url, x="justice", retrieved_at=TS)
    with pytest.raises(BadSepSource):
        make_sep_link(ENTRY_URL, x="  ", retrieved_at=TS)
    with pytest.raises(BadSepSource):
        make_sep_paste("quote", x="", retrieved_at=TS)
    with pytest.raises(BadSepSource):
        make_sep_paste("   ", x="justice", retrieved_at=TS)
    with pytest.raises(BadSepSource):
        make_sep_paste(EXCERPT, x="justice", speaker=42, retrieved_at=TS)


def test_sep_dataclass_shape_errors_raise_badsep():
    with pytest.raises(BadSepSource):
        SepEntry(origin="crawl", url=None, excerpt=None, speaker=None,
                 retrieved_at=TS)
    with pytest.raises(BadSepSource):
        SepEntry(origin=SEP_ORIGIN_LINK, url="https://plato.stanford.edu/",
                 excerpt="not allowed", speaker=None, retrieved_at=TS)


# -- F12 structural I/O absence ------------------------------------------------

def test_sep_module_takes_no_transport_and_imports_no_io():
    import search.sep as sep_module

    source = pathlib.Path(sep_module.__file__).read_text(encoding="utf-8")
    for forbidden in ("urllib.request", "dictionary.transport",
                      "urlopen", "transport.get"):
        assert forbidden not in source, forbidden

    for name, fn in vars(sep_module).items():
        if not inspect.isfunction(fn) or fn.__module__ != "search.sep":
            continue
        params = inspect.signature(fn).parameters
        for banned in ("transport", "provider", "fetch", "http", "session"):
            assert banned not in params, f"{name} takes {banned}"
        assert all(p.kind is not inspect.Parameter.VAR_KEYWORD
                   for p in params.values())


def test_sep_module_reexports_and_round_trip():
    entry = make_sep_paste(EXCERPT, x="justice", speaker="Polemarchus",
                           retrieved_at=TS)
    assert SepEntry.from_dict(entry.to_dict()) == entry
    link = make_sep_link(ENTRY_URL, x="justice", citation="Rep. I",
                         retrieved_at=TS)
    assert SepEntry.from_dict(json.loads(json.dumps(link.to_dict()))) == link
