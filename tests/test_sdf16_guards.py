"""SDF-16 F20–F26 — the unprompted-path guards (AC1/AC3 as proofs).

These tests must pass **as written**: a failure is a producer defect
(automatic code reaching web/SEP capability), never a guard problem.
Tripwire transport, host allow-list, marker scan, structural I/O absence
and the live gate together prove: no web call fires without an explicit
trigger, and unprompted paths never touch philosopher sources.
"""

from __future__ import annotations

import json
import pathlib

import pytest

import board.verdicts as V
from dictionary.chain import build_default_chain
from dictionary.model import SOURCES
from search.backend import BraveSearchBackend
from search.errors import BadSepSource
from tests.sdf5_stubs import JUSTICE, THRASYMACHUS, justice_stub
from tests.search_stubs import (
    BRAVE_KEY,
    StubSearchTransport,
    TripwireSearchTransport,
    make_provider,
)

ENTRY_URL = "https://plato.stanford.edu/entries/justice/"
EXCERPT = "Justice is the advantage of the stronger. (SEP, pasted voice)"

DICTIONARY_HOSTS = {
    "en.wiktionary.org", "api.dictionaryapi.dev", "www.dictionaryapi.com",
}

# Markers that may exist only in ``search/`` and ``tests/`` — never in the
# packages the automatic path is built from.
MARKERS = (
    "api.search.brave.com",
    "search.brave",
    "plato.stanford",
    "X-Subscription-Token",
)


def _tripwire_service(root):
    """Chain over the Justice fixtures + a provider wired to a tripwire."""
    from server.service import BoardService

    provider = make_provider(
        transport=TripwireSearchTransport(), clock=lambda: "2026-09-13T00:00:00+00:00")
    return BoardService(
        root,
        chain=build_default_chain(justice_stub(), clock=lambda: "2026-09-13"),
        clock=lambda: "2026-09-13T00:00:00+00:00",
        search_provider=provider,
    ), provider


# -- F20 full unprompted lifecycle over a tripwire ----------------------------

def test_unprompted_lifecycle_never_fires_the_provider(tmp_path):
    svc, provider = _tripwire_service(tmp_path / "store")
    tripwire = provider.transport
    opened = svc.open_board(JUSTICE)                      # canonical pull
    bid = opened.board_id
    machine = svc.machine(bid)
    h = {name: machine.enroll_handle(name)
         for name in ("Cephalus", "Polemarchus", "Thrasymachus")}
    svc.claim_canonical(bid, claimant_display="Cephalus")
    ce, q = machine.open_refutation_q("n1", "3a", opened_by=h["Cephalus"])
    svc.cast_vote(bid, q, "stands", handle_id=h["Cephalus"])
    svc.record_ambient_vote(bid, q, "rebutted", handle_id=h["Thrasymachus"])
    svc.revise(bid, THRASYMACHUS + " (revised)", claimant_display="Cephalus")
    svc.view(bid)
    svc.scoreboard(bid, "n2")
    svc.sync_registry(bid)
    svc.boards_list()
    svc.list_boards(JUSTICE)
    svc.read_events(bid)
    svc.on_demand(bid)
    svc.counterexamples(bid)
    svc.canonicals(bid)
    svc.provenance_map(bid)
    assert tripwire.calls == [], "an unprompted path touched the web seam"


def test_deliberate_trigger_fires_exactly_once(tmp_path):
    svc, provider = _tripwire_service(tmp_path / "store")
    opened = svc.open_board(JUSTICE)
    with pytest.raises(AssertionError):
        # one deliberate trigger hits the tripwire exactly once (proves the
        # wiring itself is live) — and it is the CALLER that fired it
        provider.search("justice", query=None, limit=5)
    assert len(provider.transport.calls) == 1


# -- F21 ambient tallies stay silent ------------------------------------------

def test_ambient_tally_and_views_stay_silent(tmp_path):
    from tests.search_stubs import CountingBackend

    counting = CountingBackend(clock=lambda: "2026-09-13T00:00:00+00:00")
    from server.service import BoardService

    svc = BoardService(
        tmp_path / "store",
        chain=build_default_chain(justice_stub(), clock=lambda: "2026-09-13"),
        clock=lambda: "2026-09-13T00:00:00+00:00",
        search_provider=counting,
    )
    opened = svc.open_board(JUSTICE)
    bid = opened.board_id
    machine = svc.machine(bid)
    h = {name: machine.enroll_handle(name)
         for name in ("Cephalus", "Polemarchus", "Thrasymachus")}
    svc.claim_canonical(bid, claimant_display="Cephalus")
    ce, q = machine.open_refutation_q("n1", "3a", opened_by=h["Cephalus"])
    machine.cast(q, h["Cephalus"], "explicit", "stands")
    machine.cast(q, h["Polemarchus"], "explicit", "stands")
    machine.record_ambient(q, h["Thrasymachus"], "rebutted")
    V.tally(machine.state, q)                    # ambient read paths
    V.census(machine.state, q)
    V.standing_counts(machine.state, ce)
    V.is_standing(machine.state, ce)
    svc.view(bid)
    svc.scoreboard(bid, "n1")
    assert counting.searches == [], "a tally path performed a web search"


# -- F22 the default pull reaches dictionary hosts only ------------------------

def test_default_pull_hits_dictionary_hosts_only(tmp_path):
    stub = justice_stub()
    from server.service import BoardService

    svc = BoardService(
        tmp_path / "store", chain=build_default_chain(stub,
                                                      clock=lambda: "2026-09-13"),
        clock=lambda: "2026-09-13T00:00:00+00:00")
    svc.open_board(JUSTICE)
    assert stub.calls, "the fixture must have pulled canonicals"
    for url in stub.calls:
        host = url.split("/")[2] if "://" in url else url
        assert host in DICTIONARY_HOSTS, url
    for marker in ("brave", "plato", "stanford", "search.brave"):
        assert not any(marker in url for url in stub.calls), marker


# -- F23 marker scan confined to search/ + tests/ -------------------------------

def test_marker_scan_boards_only_packages():
    for package in ("board", "dictionary", "server"):
        root = pathlib.Path(package)
        assert root.is_dir()
        for path in sorted(root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for marker in MARKERS:
                assert marker not in text, f"{path}: {marker}"
    # and the markers really do live only where they are allowed
    search_root = pathlib.Path("search")
    assert any(MARKERS[0] in p.read_text(encoding="utf-8")
               for p in search_root.rglob("*.py"))


# -- F24 the dictionary chain is unchanged vocabulary ---------------------------

def test_chain_vocabulary_unchanged_and_chain_has_no_search(tmp_path):
    assert SOURCES == ("wiktionary", "free-dictionary", "merriam-webster")
    stub = justice_stub()
    from server.service import BoardService

    svc = BoardService(
        tmp_path / "store", chain=build_default_chain(stub,
                                                      clock=lambda: "2026-09-13"),
        clock=lambda: "2026-09-13T00:00:00+00:00")
    opened = svc.open_board(JUSTICE)
    snapshot = svc.canonicals(opened.board_id)
    cite_sources = {
        cite["source"]
        for sense in snapshot["senses"]
        for cite in sense["cites"]
    }
    assert cite_sources <= set(SOURCES)
    chain = svc._chain()
    # ``search`` is the pre-existing SDF-3 get() alias — no web capability,
    # no SEP capability, nothing the automatic path could arm.
    for banned in ("brave", "sep", "web"):
        assert not hasattr(chain, banned), banned
    import inspect

    assert "brave" not in inspect.getsource(type(chain)).casefold()
    assert "stanford" not in inspect.getsource(type(chain)).casefold()
    assert "search" not in json.dumps(snapshot.get("state", ""))


# -- F25 SEP admission performs zero I/O ----------------------------------------

def test_sep_admission_makes_zero_transport_calls(tmp_path):
    from server.service import BoardService

    stub = StubSearchTransport([])               # any call raises
    provider = make_provider(transport=stub, clock=lambda: "2026-09-13")
    svc = BoardService(
        tmp_path / "store",
        chain=build_default_chain(justice_stub(), clock=lambda: "2026-09-13"),
        clock=lambda: "2026-09-13T00:00:00+00:00",
        search_provider=provider)
    bid = svc.open_board(JUSTICE).board_id
    svc.attach_sep(bid, triggered_by="Cephalus", url=ENTRY_URL)
    svc.attach_sep(bid, triggered_by="Cephalus", excerpt=EXCERPT,
                   speaker="Polemarchus")
    assert stub.calls == []


def test_sep_admission_needs_no_provider_at_all(tmp_path):
    from server.service import BoardService

    svc = BoardService(
        tmp_path / "store",
        chain=build_default_chain(justice_stub(), clock=lambda: "2026-09-13"),
        clock=lambda: "2026-09-13T00:00:00+00:00")
    bid = svc.open_board(JUSTICE).board_id
    row = svc.attach_sep(bid, triggered_by="Cephalus", url=ENTRY_URL)
    assert row["source"] == "philosopher-sep"


# -- F26 the live gate still blocks the default transport ------------------------

def test_live_gate_blocks_the_default_search_transport():
    backend = BraveSearchBackend("k")            # default header transport
    with pytest.raises(AssertionError):
        backend.search("justice")


def test_bad_sep_source_is_both_search_error_and_value_error():
    from search.errors import SearchError

    assert issubclass(BadSepSource, SearchError)
    assert issubclass(BadSepSource, ValueError)
