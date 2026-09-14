"""AC2 — the first claim auto-activates, and carries its source tag.

A canonical claim is a *verbatim copy* of one cached sense plus the cites
that justify it; an original is authored text with no source tag. Activation
itself is not implemented here: ``VerdictMachine.register_node`` makes the new
node the single active one, so the first claim activates for free (and a
second first-claim is refused rather than silently becoming a revision).
"""

from __future__ import annotations

import pytest

from board.machine import BoardClosed
from server.errors import (
    BlankClaim,
    EmptyCanonicals,
    NoCanonicals,
    UnknownBoard,
    UnknownSense,
)
from server.model import SOURCE_TAG
from tests.sdf5_stubs import (
    S0,
    S1,
    THRASYMACHUS,
    empty_chain,
    make_service,
)


def _counts(service, board_id):
    return (len(service.journals.read_all(board_id)),
            len(service.meta.read_events(board_id)))


def svc_root(service):
    return service.root


def test_first_claim_auto_activates(sdf5_open):
    ctx = sdf5_open
    service, bid = ctx.service, ctx.board_id
    before = len(service.journals.read_all(bid))
    result = service.claim_canonical(bid, claimant_display="Cephalus")
    state = service.state(bid)
    assert result.version == 1
    assert result.is_active is True
    assert result.prev_node_id is None
    assert result.is_revision is False
    assert result.frozen_q_ids == []
    assert state.active_node_id == result.node_id == "n1"
    assert state.nodes["n1"].is_active is True
    journal = service.journals.read_all(bid)
    assert [e["type"] for e in journal[before:]] == ["node_registered"]
    # exactly one active node is the machine's invariant, view agrees
    assert [n["node_id"] for n in service.view(bid)["nodes"]
            if n["is_active"]] == ["n1"]


def test_canonical_claim_is_source_tagged(sdf5_open):
    ctx = sdf5_open
    service, bid = ctx.service, ctx.board_id
    result = service.claim_canonical(bid, "s0", claimant_display="Cephalus")
    assert result.text == S0                      # byte-identical copy
    assert service.state(bid).nodes["n1"].text == S0
    provenance = result.provenance
    assert provenance["source"] == SOURCE_TAG
    assert provenance["kind"] == "canonical"
    assert provenance["sense_id"] == "s0"
    assert provenance["gloss"] == S0
    assert provenance["pos"] == "noun"
    assert provenance["wiktionary_sense_no"] == 1
    assert provenance["cite_sources"] == ["wiktionary", "free-dictionary"]
    assert provenance["pulled_at"] == "2026-09-13"
    for cite in provenance["cites"]:
        assert cite["url"].startswith("https://")
        assert cite["access_date"] == "2026-09-13"
        assert cite["license"]
    assert provenance["claimed_by"] == ctx.h["Cephalus"]
    # durable: readable from the sidecar alone, after a restart
    assert service.provenance(bid, "n1") == provenance


def test_claim_specific_sense_and_unknown_sense(sdf5_open):
    ctx = sdf5_open
    service, bid = ctx.service, ctx.board_id
    before = _counts(service, bid)
    with pytest.raises(UnknownSense):
        service.claim_canonical(bid, "s9", claimant_display="Cephalus")
    assert _counts(service, bid) == before, "a bad sense id must not mutate"
    result = service.claim_canonical(bid, "s1",
                                    claimant_display="Thrasymachus")
    assert result.text == S1
    assert result.provenance["sense_id"] == "s1"
    assert _counts(service, bid) == (before[0] + 1, before[1] + 1)


def test_original_claim_is_untagged(sdf5_open):
    ctx = sdf5_open
    service, bid = ctx.service, ctx.board_id
    result = service.claim_original(bid, THRASYMACHUS,
                                   claimant_display="Thrasymachus")
    assert result.text == THRASYMACHUS            # verbatim, not normalized
    assert result.provenance["kind"] == "original"
    assert result.provenance["source"] is None
    assert result.provenance["cites"] == []
    assert result.provenance["cite_sources"] == []
    assert result.provenance["sense_id"] is None
    assert service.state(bid).nodes["n1"].text == THRASYMACHUS


def test_blank_claims_and_missing_cache_are_refused_without_writing(sdf5_open):
    ctx = sdf5_open
    service, bid = ctx.service, ctx.board_id
    before = _counts(service, bid)
    for bad in ("", "   ", "\n\t", None, 42):
        with pytest.raises(BlankClaim):
            service.claim_original(bid, bad, claimant_display="Cephalus")
    assert _counts(service, bid) == before

    deferred = make_service(svc_root(service) / "other", chain=empty_chain())
    opened = deferred.open_board("Justice", pull_canonicals=False)
    assert deferred.canonicals(opened.board_id) is None
    with pytest.raises(NoCanonicals):
        deferred.claim_canonical(opened.board_id,
                                claimant_display="Cephalus")
    assert deferred.journals.read_all(opened.board_id)
    assert deferred.meta.read_events(opened.board_id) == []


def test_claim_on_closed_board_refused(sdf5_open):
    ctx = sdf5_open
    service, bid, machine = ctx.service, ctx.board_id, ctx.machine
    service.claim_original(bid, THRASYMACHUS, claimant_display="Cephalus")
    close_q = machine.propose_close(opened_by=ctx.h["Cephalus"])
    for who in ("Cephalus", "Polemarchus"):
        machine.cast(close_q, ctx.h[who], "explicit", "for")
    assert machine.is_closed()
    assert service.view(bid)["status"] == "closed"
    with pytest.raises(BoardClosed):
        service.claim_canonical(bid, claimant_display="Thrasymachus")
    with pytest.raises(BoardClosed):
        service.revise(bid, "a new attempt", claimant_display="Thrasymachus")
    assert len(service.meta.read_events(bid)) == 1


def test_claimant_is_enrolled_once(sdf5_open):
    ctx = sdf5_open
    service, bid = ctx.service, ctx.board_id
    first = service.claim_original(bid, THRASYMACHUS,
                                  claimant_display="Protagoras")
    second = service.revise(bid, "Justice is teaching what is good.",
                           claimant_display="Protagoras")
    assert first.provenance["claimed_by"] == second.provenance["claimed_by"]
    handles = service.state(bid).handles.values()
    matches = [h for h in handles if h.display == "Protagoras"]
    assert len(matches) == 1, "one person, one handle"
    # the three fixture humans are untouched
    assert len(list(handles)) == 4


def test_empty_canonicals_still_allow_a_board_and_an_original(tmp_path):
    service = make_service(tmp_path / "store", chain=empty_chain())
    opened = service.open_board("Justice")
    snapshot = service.canonicals(opened.board_id)
    assert snapshot["state"] == "empty"
    assert snapshot["senses"] == []
    with pytest.raises(EmptyCanonicals):
        service.claim_canonical(opened.board_id,
                               claimant_display="Cephalus")
    result = service.claim_original(opened.board_id, THRASYMACHUS,
                                   claimant_display="Cephalus")
    assert result.is_active is True
    assert service.view(opened.board_id)["canonicals"]["state"] == "empty"


def test_claim_on_unknown_board(sdf5_open):
    with pytest.raises(UnknownBoard):
        sdf5_open.service.claim_original("no-such-board", "text",
                                        claimant_display="Cephalus")
