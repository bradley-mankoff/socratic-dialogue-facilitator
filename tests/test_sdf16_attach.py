"""SDF-16 F13–F19 — the explicit triggers through the service.

Every trigger is deliberate: ``search_counterexamples`` (one backend call)
and ``attach_sep`` (zero I/O) append labeled events to the meta sidecar —
never the journal, never the canvas, never the canonical cache. All
stubbed: the dictionary chain answers from fixtures, the web provider
from ``StubSearchTransport``; the autouse ``no_live_network`` guard holds.
"""

from __future__ import annotations

import json

import pytest

from dictionary.chain import build_default_chain
from server.errors import UnknownBoard
from server.model import SEARCH_RECORDED, SEP_ADMITTED
from server.service import BoardService
from search.errors import BadSepSource, NoSearchProvider
from tests.search_stubs import (
    TS,
    StubSearchTransport,
    brave_response,
    make_provider,
)
from tests.sdf5_stubs import JUSTICE, THRASYMACHUS, justice_stub

ENTRY_URL = "https://plato.stanford.edu/entries/justice/"
EXCERPT = "  \"Justice is the advantage of the stronger.\" — Republic 338c  "


def _service(root, provider=None) -> BoardService:
    return BoardService(
        root,
        chain=build_default_chain(justice_stub(), clock=lambda: "2026-09-13"),
        clock=lambda: TS,
        search_provider=provider,
    )


def _provider_with(n_calls: int = 2):
    return make_provider(
        transport=StubSearchTransport([brave_response() for _ in range(n_calls)]),
        clock=lambda: TS,
    )


@pytest.fixture
def open_ctx(tmp_path):
    """Open Justice board + counting provider service (no claim noise)."""
    svc = _service(tmp_path / "store", provider=_provider_with(4))
    opened = svc.open_board(JUSTICE)
    return svc, opened.board_id


# -- F13 the search event ---------------------------------------------------

def test_search_appends_one_meta_event_with_envelope(open_ctx):
    svc, bid = open_ctx
    payload = svc.search_counterexamples(bid, triggered_by="Cephalus")
    events = svc.meta.read_events(bid)
    assert [e["type"] for e in events] == [SEARCH_RECORDED]
    envelope = events[0]
    assert envelope["seq"] == 1 and envelope["board_id"] == bid
    assert envelope["ts"] == TS
    assert envelope["payload"] is payload or envelope["payload"] == payload
    assert payload["search_id"] == "srch1"
    assert payload["requested_by"] == "Cephalus"
    assert payload["kind"] == "web-search" and payload["canonical"] is False
    # the durable home is the meta sidecar, not the journal
    sidecar = svc.meta.path_for(bid)
    assert sidecar.name == "meta.jsonl" and sidecar.exists()


def test_trigger_cost_is_exactly_one_backend_call(open_ctx):
    svc, bid = open_ctx
    stub = svc.search_provider.transport
    svc.search_counterexamples(bid, triggered_by="Cephalus")
    assert len(stub.calls) == 1
    assert stub.urls[0].startswith("https://api.search.brave.com/res/v1/web/search")


# -- F14 journal-free writes -------------------------------------------------

def test_triggers_never_touch_journal_or_canvas(open_ctx):
    svc, bid = open_ctx
    svc.machine(bid).enroll_handle("Cephalus")
    svc.claim_canonical(bid, claimant_display="Cephalus")
    before = svc.journals.read_all(bid)
    state_before = svc.state(bid)
    svc.search_counterexamples(bid, triggered_by="Cephalus")
    svc.attach_sep(bid, triggered_by="Cephalus", url=ENTRY_URL)
    svc.attach_sep(bid, triggered_by="Cephalus", excerpt=EXCERPT,
                   speaker="Thrasymachus")
    assert svc.journals.read_all(bid) == before
    assert svc.state(bid) == state_before
    # handles/nodes untouched: no enrollment happened for the display strings
    assert svc.state(bid).handles == state_before.handles
    assert [n.node_id for n in svc.state(bid).nodes.values()] == ["n1"]
    # the meta sidecar carries exactly the three on-demand events, not claims
    assert [e["type"] for e in svc.meta.read_events(bid)] == [
        "claim_recorded", "search_recorded", "sep_admitted", "sep_admitted"]


def test_triggers_are_replayed_from_disk_after_reload(tmp_path):
    svc = _service(tmp_path / "store", provider=_provider_with(1))
    bid = svc.open_board(JUSTICE).board_id
    svc.search_counterexamples(bid, triggered_by="Cephalus")
    svc.attach_sep(bid, triggered_by="Cephalus", excerpt=EXCERPT,
                   speaker="Cephalus")
    reopened = BoardService.open(tmp_path / "store")
    assert reopened.on_demand(bid) == svc.on_demand(bid)
    assert reopened.counterexamples(bid)["sep"][0]["excerpt"] == EXCERPT


# -- F15 SEP admits: link + paste, ids, labels --------------------------------

def test_link_and_paste_admits_get_ids_and_labels(open_ctx):
    svc, bid = open_ctx
    link = svc.attach_sep(bid, triggered_by="Cephalus", url=ENTRY_URL)
    paste = svc.attach_sep(bid, triggered_by="Cephalus", excerpt=EXCERPT,
                           speaker="Thrasymachus",
                           citation="Republic 338c")
    assert link["sep_id"] == "sep1" and paste["sep_id"] == "sep2"
    assert [e["seq"] for e in svc.meta.read_events(bid, SEP_ADMITTED)] == [1, 2]
    assert link["origin"] == "link" and link["url"] == ENTRY_URL
    assert link["source"] == "philosopher-sep"
    assert link["source_label"] == (
        "Stanford Encyclopedia of Philosophy (philosopher source)")
    assert paste["origin"] == "paste"
    assert paste["excerpt"] == EXCERPT            # verbatim, whitespace kept
    assert paste["speaker"] == "Thrasymachus"     # display string, not handle
    assert link["canonical"] is False and paste["canonical"] is False
    assert link["triggered_by"] == "Cephalus"


def test_bare_slug_expands_through_attach(open_ctx):
    svc, bid = open_ctx
    entry = svc.attach_sep(bid, triggered_by="Cephalus", url="justice")
    assert entry["url"] == ENTRY_URL
    assert entry["origin"] == "link"


def test_attach_refuses_both_neither_and_evil_input_with_zero_writes(open_ctx):
    svc, bid = open_ctx
    for kwargs in ({}, {"url": ENTRY_URL, "excerpt": EXCERPT}):
        with pytest.raises(BadSepSource):
            svc.attach_sep(bid, triggered_by="Cephalus", **kwargs)
    with pytest.raises(BadSepSource):
        svc.attach_sep(bid, triggered_by="Cephalus",
                       url="http://plato.stanford.edu/entries/justice/")
    with pytest.raises(BadSepSource):
        svc.attach_sep(bid, triggered_by="Cephalus",
                       url="https://iep.utm.edu/thrasymachus/")
    with pytest.raises(BadSepSource):
        svc.attach_sep(bid, triggered_by="Cephalus", excerpt="   ")
    with pytest.raises(ValueError):
        svc.attach_sep(bid, triggered_by="  ", url=ENTRY_URL)
    assert svc.meta.read_events(bid, SEP_ADMITTED) == []
    assert svc.meta.read_events(bid) == []


# -- F16 view surface ---------------------------------------------------------

def test_view_surfaces_on_demand_section_canonicals_untouched(open_ctx):
    svc, bid = open_ctx
    view_before = svc.view(bid)
    svc.search_counterexamples(bid, triggered_by="Cephalus")
    svc.attach_sep(bid, triggered_by="Cephalus", url=ENTRY_URL)
    svc.attach_sep(bid, triggered_by="Cephalus", excerpt=EXCERPT,
                   speaker="Thrasymachus")
    view_after = svc.view(bid)
    assert (json.dumps(view_after["canonicals"])
            == json.dumps(view_before["canonicals"]))
    section = view_after["on_demand"]
    assert view_after["counterexamples"] == section   # alias keys, one body
    assert section["kind"] == "counterexamples"
    assert section["label"] == (
        "counterexample material — web/SEP voices; never canonicals")
    search_row = section["searches"][0]
    assert search_row["kind"] == "web-search"
    assert search_row["source"] == "brave-web"
    assert search_row["canonical"] is False
    assert [h["source"] for h in search_row["hits"]] == ["brave-web"] * 3
    sep_row = section["sep"][0]
    assert sep_row["source"] == "philosopher-sep"
    assert sep_row["kind"] == "sep" and sep_row["canonical"] is False
    assert json.loads(json.dumps(view_after)) == view_after


# -- F17 no provider, silent dictionary ---------------------------------------

def test_no_provider_refuses_before_io_and_dictionary_stays_silent(tmp_path):
    stub = justice_stub()
    svc = _service(tmp_path / "store")
    opened = svc.open_board(JUSTICE, pull_canonicals=False)
    calls_before = len(stub.calls)
    with pytest.raises(NoSearchProvider):
        svc.search_counterexamples(opened.board_id, triggered_by="Cephalus")
    assert len(stub.calls) == calls_before
    # SEP admission needs no provider at all
    payload = svc.attach_sep(opened.board_id, triggered_by="Cephalus",
                             url=ENTRY_URL)
    assert payload["source"] == "philosopher-sep"


# -- F18 board resolution + closed boards --------------------------------------

def test_unknown_board_refuses_with_zero_writes(tmp_path):
    svc = _service(tmp_path / "store", provider=_provider_with(1))
    with pytest.raises(UnknownBoard):
        svc.search_counterexamples("nope--none--999", triggered_by="Cephalus")
    with pytest.raises(UnknownBoard):
        svc.attach_sep("nope--none--999", triggered_by="Cephalus",
                       url=ENTRY_URL)
    with pytest.raises(UnknownBoard):
        svc.on_demand("nope--none--999")
    assert svc.search_provider.transport.calls == []
    assert not (tmp_path / "store" / "nope--none--999").exists()


def test_triggers_work_on_closed_boards_writing_meta_only(tmp_path):
    svc = _service(tmp_path / "store", provider=_provider_with(1))
    opened = svc.open_board(JUSTICE)
    bid = opened.board_id
    machine = svc.machine(bid)
    h = {name: machine.enroll_handle(name)
         for name in ("Cephalus", "Polemarchus", "Thrasymachus")}
    svc.claim_original(bid, THRASYMACHUS, claimant_display="Cephalus")
    qc = svc.propose_close(bid, opened_by=h["Cephalus"])
    # census is the 3-handle open roster: the second 'for' is the strict
    # majority that settles the close Q and closes the board
    for name in ("Cephalus", "Polemarchus"):
        svc.governance_vote(bid, qc, h[name], "for")
    assert svc.state(bid).status == "closed"
    journal_after_close = svc.journals.read_all(bid)

    search_row = svc.search_counterexamples(bid, triggered_by="Thrasymachus")
    sep_row = svc.attach_sep(bid, triggered_by="Thrasymachus", url=ENTRY_URL)
    assert search_row["state"] == "ok"
    assert sep_row["sep_id"] == "sep1"
    assert svc.journals.read_all(bid) == journal_after_close   # journal frozen
    assert svc.view(bid)["on_demand"]["searches"], "closed boards still read"


def test_fresh_board_reads_empty_on_demand_with_zero_calls(tmp_path):
    counting = _CountingProvider()
    svc = _service(tmp_path / "store", provider=counting)
    opened = svc.open_board(JUSTICE, pull_canonicals=False)
    assert svc.on_demand(opened.board_id) == {"searches": [], "sep": []}
    assert svc.view(opened.board_id)["on_demand"] == {
        "kind": "counterexamples",
        "label": "counterexample material — web/SEP voices; never canonicals",
        "searches": [], "sep": [],
    }
    assert counting.searches == []


# -- F19 re-triggers ------------------------------------------------------------

def test_second_search_bumps_seq_and_calls_provider_again(open_ctx):
    svc, bid = open_ctx
    stub = svc.search_provider.transport
    first = svc.search_counterexamples(bid, triggered_by="Cephalus")
    second = svc.search_counterexamples(bid, triggered_by="Polemarchus",
                                        query="justice thrasymachus",
                                        count=3)
    events = svc.meta.read_events(bid, SEARCH_RECORDED)
    assert [e["seq"] for e in events] == [1, 2]
    assert [e["payload"]["search_id"] for e in events] == ["srch1", "srch2"]
    assert first["search_id"] == "srch1" and second["search_id"] == "srch2"
    assert second["query"] == "justice thrasymachus"
    assert len(stub.calls) == 2
    # never cached into canonicals: the canonical snapshot is untouched
    canon = svc.canonicals(bid)
    assert "hits" not in canon and canon["state"] == "ok"


class _CountingProvider:
    """Minimal recording backend (no I/O) for zero-call assertions."""

    def __init__(self) -> None:
        self.searches: list[dict] = []

    def search(self, x, *, query=None, limit=5):
        from search.model import CounterexampleResult

        self.searches.append({"x": x, "query": query, "limit": limit})
        return CounterexampleResult(x=x, query=query or f"{x} counterexample",
                                    state="unavailable",
                                    detail="counting backend", engine=None,
                                    retrieved_at=TS)
