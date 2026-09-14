"""AC3 — a revision creates a NEW version node and never edits history.

Three layers of proof, because "never edits history" is a claim about bytes:

1. the journal grows by exactly the machine's own revision events and the
   bytes already written are a prefix of the bytes after;
2. the superseded node's text/version and its frozen questions are unchanged;
3. the sidecar carries the ``carried_unvoted`` event SDF-7 folds into a tray,
   and replay of the journal rebuilds the identical state.

Nothing here re-derives a verdict: ``outcome``/``stands``/``rebutted``/
``census_size``/``carried`` are read out of ``board.verdicts`` after the
freeze, and ``carried`` follows ``is_standing`` (ties stand) rather than
``outcome`` (a tie has no winner).

Note on ``settled``: a refutation question is only ever ``open`` then
``frozen`` (``VerdictMachine._settle_tail`` reports a refutation verdict
without settling it), so the carried set is "every CE that was still open
when the claim was superseded" — losing CEs are emitted with
``carried: false`` as the faithful record for SDF-7 to filter.
"""

from __future__ import annotations

from collections import Counter
from types import SimpleNamespace

import pytest

import board.verdicts as V
from board.machine import fold_events
from server.errors import ClaimAlreadyActive, NoActiveClaim
from server.model import CLAIM_RECORDED, CLAIM_REVISED, TRAY_NAME
from tests.sdf5_stubs import S0, S1, THRASYMACHUS, justice_chain, make_service

REVISION_KEYS = {
    "tray", "prev_node_id", "new_node_id", "prev_text", "new_text",
    "prev_version", "new_version", "frozen_q_ids", "unresolved_ces",
    "prev_node_refuted", "in_response_to", "claimed_by",
}


@pytest.fixture
def attacked(sdf5_open):
    """Board with a canonical v1 and two counterexamples under vote.

    ce1/q1: 2–1 "stands" out of a census of 3 → standing and refuting.
    ce2/q2: 1–2 "stands" → losing, so it must NOT be carried.
    """
    ctx = sdf5_open
    service, machine, h = ctx.service, ctx.machine, ctx.h
    service.claim_canonical(ctx.board_id, claimant_display="Cephalus")
    ce1, q1 = machine.open_refutation_q("n1", "3a", opened_by=h["Cephalus"])
    ce2, q2 = machine.open_refutation_q("n1", "3b", opened_by=h["Polemarchus"])
    machine.cast(q1, h["Cephalus"], "explicit", "stands")
    machine.cast(q1, h["Polemarchus"], "explicit", "stands")
    machine.cast(q1, h["Thrasymachus"], "explicit", "rebutted")
    machine.cast(q2, h["Cephalus"], "explicit", "stands")
    machine.cast(q2, h["Polemarchus"], "explicit", "rebutted")
    machine.cast(q2, h["Thrasymachus"], "explicit", "rebutted")
    return SimpleNamespace(service=service, board_id=ctx.board_id,
                           machine=machine, h=h, record=ctx.record,
                           ce1=ce1, q1=q1, ce2=ce2, q2=q2)


def _counts(service, board_id):
    return (len(service.journals.read_all(board_id)),
            len(service.meta.read_events(board_id)))


def test_revision_creates_a_new_version_node(attacked):
    ctx = attacked
    service, bid = ctx.service, ctx.board_id
    path = service.journals.path_for(bid)
    before_bytes = path.read_bytes()
    v1_text = service.state(bid).nodes["n1"].text

    result = service.revise(bid, THRASYMACHUS,
                            claimant_display="Thrasymachus",
                            in_response_to=ctx.ce1)
    state = service.state(bid)
    assert (result.version, result.node_id) == (2, "n2")
    assert result.is_active is True and result.is_revision is True
    assert result.prev_node_id == "n1"
    assert state.active_node_id == "n2"
    assert state.nodes["n2"].ce_ids == []
    assert state.nodes["n2"].status == "open"
    # history untouched: the v1 row still says what it said, byte for byte
    assert state.nodes["n1"].text == S0 == v1_text
    assert state.nodes["n1"].version == 1
    assert state.nodes["n1"].is_active is False
    assert state.canvas is None
    # append-only at the byte level: what was written is a prefix of what is
    after_bytes = path.read_bytes()
    assert after_bytes.startswith(before_bytes)
    assert len(after_bytes) > len(before_bytes)


def test_revision_freezes_open_questions(attacked):
    ctx = attacked
    service, bid = ctx.service, ctx.board_id
    result = service.revise(bid, S1, claimant_display="Polemarchus")
    state = service.state(bid)
    assert sorted(result.frozen_q_ids) == sorted([ctx.q1, ctx.q2])
    for ce_id, q_id in ((ctx.ce1, ctx.q1), (ctx.ce2, ctx.q2)):
        q = state.questions[q_id]
        assert q.status == "frozen"
        assert q.outcome == V.refutation_outcome(state, ce_id)
    # re-voting a superseded claim is refused by the machine, not by us
    from board.machine import NodeFrozen
    with pytest.raises(NodeFrozen):
        service.machine(bid).cast(ctx.q1, ctx.h["Thrasymachus"], "explicit",
                                 "rebutted")


def test_revision_event_shape_is_the_sdf7_contract(attacked):
    ctx = attacked
    service, bid = ctx.service, ctx.board_id
    service.revise(bid, THRASYMACHUS, claimant_display="Thrasymachus",
                   in_response_to=ctx.ce1)
    events = service.read_events(bid, CLAIM_REVISED)
    assert len(events) == 1
    event = events[0]
    assert event["seq"] == 3     # claim_recorded(1) for v1, (2) for this claim
    assert event["ts"] == "2026-09-13T00:00:00+00:00"   # injected clock
    assert event["board_id"] == bid
    payload = event["payload"]
    assert set(payload) == REVISION_KEYS
    assert payload["tray"] == TRAY_NAME
    assert (payload["prev_node_id"], payload["new_node_id"]) == ("n1", "n2")
    assert payload["prev_text"] == S0
    assert payload["new_text"] == THRASYMACHUS
    assert (payload["prev_version"], payload["new_version"]) == (1, 2)
    assert payload["in_response_to"] == ctx.ce1
    assert payload["claimed_by"] == ctx.h["Thrasymachus"]
    assert payload["prev_node_refuted"] is True
    assert sorted(payload["frozen_q_ids"]) == sorted([ctx.q1, ctx.q2])
    assert [row["ce_id"] for row in payload["unresolved_ces"]] == [ctx.ce1,
                                                                  ctx.ce2]


def test_carried_tracks_is_standing_not_outcome(attacked):
    ctx = attacked
    service, bid = ctx.service, ctx.board_id
    result = service.revise(bid, THRASYMACHUS,
                            claimant_display="Thrasymachus")
    rows = {row["ce_id"]: row
            for row in result.revision_event["payload"]["unresolved_ces"]}
    ce1 = rows[ctx.ce1]
    assert (ce1["stands"], ce1["rebutted"], ce1["census_size"]) == (2, 1, 3)
    assert ce1["outcome"] == "stands" and ce1["carried"] is True
    assert ce1["q_status"] == "frozen"
    assert ce1["node_id"] == "n1" and ce1["shape"] == "3a"
    ce2 = rows[ctx.ce2]
    assert (ce2["stands"], ce2["rebutted"], ce2["census_size"]) == (1, 2, 3)
    assert ce2["outcome"] is None and ce2["carried"] is False
    assert ce2["shape"] == "3b"
    # SDF-7's documented fold: carried-only, deduped by ce_id last-wins
    tray = [e for e in rows.values() if e["carried"]]
    assert [e["ce_id"] for e in tray] == [ctx.ce1]


def test_tie_is_carried_though_it_has_no_outcome(sdf5_open):
    """1–1 stands (issue 02) yet has no winner: carried True, outcome None.

    Deriving ``carried`` from ``outcome`` would drop the live objection.
    """
    ctx = sdf5_open
    service, machine, bid = ctx.service, ctx.machine, ctx.board_id
    service.claim_original(bid, THRASYMACHUS, claimant_display="Cephalus")
    ce, q = machine.open_refutation_q("n1", "3a",
                                      opened_by=ctx.h["Polemarchus"])
    machine.cast(q, ctx.h["Cephalus"], "explicit", "stands")
    machine.cast(q, ctx.h["Polemarchus"], "explicit", "rebutted")
    result = service.revise(bid, "Justice is reciprocity.",
                            claimant_display="Thrasymachus")
    row = result.revision_event["payload"]["unresolved_ces"][0]
    assert (row["stands"], row["rebutted"], row["census_size"]) == (1, 1, 3)
    assert row["outcome"] is None
    assert row["carried"] is True
    assert result.revision_event["payload"]["prev_node_refuted"] is False


def test_losing_counterexample_is_recorded_but_not_carried(sdf5_open):
    """A 0–3 rebuttal stays in the event as the faithful record (carried false)."""
    ctx = sdf5_open
    service, machine, bid = ctx.service, ctx.machine, ctx.board_id
    service.claim_original(bid, THRASYMACHUS, claimant_display="Cephalus")
    ce, q = machine.open_refutation_q("n1", "3a",
                                      opened_by=ctx.h["Polemarchus"])
    for who in ("Cephalus", "Polemarchus", "Thrasymachus"):
        machine.cast(q, ctx.h[who], "explicit", "rebutted")
    result = service.revise(bid, "Justice is reciprocity.",
                            claimant_display="Thrasymachus")
    row = result.revision_event["payload"]["unresolved_ces"][0]
    assert (row["stands"], row["rebutted"]) == (0, 3)
    assert row["carried"] is False and row["outcome"] is None
    assert row["q_status"] == "frozen"


def test_a_clean_node_revises_with_an_empty_tray(sdf5_open):
    """No objections at all is the normal case, not an error: ``[]``."""
    ctx = sdf5_open
    service, bid = ctx.service, ctx.board_id
    service.claim_original(bid, THRASYMACHUS, claimant_display="Cephalus")
    result = service.revise(bid, S1, claimant_display="Polemarchus")
    assert result.revision_event["payload"]["unresolved_ces"] == []
    assert result.revision_event["payload"]["frozen_q_ids"] == []
    assert result.revision_event["payload"]["prev_node_refuted"] is False


def test_revise_without_a_claim_and_bad_response_target(sdf5_open):
    ctx = sdf5_open
    service, bid = ctx.service, ctx.board_id
    before = _counts(service, bid)
    with pytest.raises(NoActiveClaim):
        service.revise(bid, THRASYMACHUS, claimant_display="Cephalus")
    assert _counts(service, bid) == before
    service.claim_original(bid, THRASYMACHUS, claimant_display="Cephalus")
    with pytest.raises(ValueError):
        service.revise(bid, S1, claimant_display="Cephalus",
                       in_response_to="ce99")
    assert _counts(service, bid) == (before[0] + 1, before[1] + 1)


def test_second_first_claim_is_refused_not_silently_revised(sdf5_open):
    """Crisp intent: v1 creation and v2+ lineage are different operations."""
    ctx = sdf5_open
    service, bid = ctx.service, ctx.board_id
    service.claim_original(bid, THRASYMACHUS, claimant_display="Cephalus")
    before = _counts(service, bid)
    with pytest.raises(ClaimAlreadyActive):
        service.claim_original(bid, S1, claimant_display="Polemarchus")
    with pytest.raises(ClaimAlreadyActive):
        service.claim_canonical(bid, claimant_display="Polemarchus")
    assert _counts(service, bid) == before
    assert service.state(bid).active_node_id == "n1"


def test_full_lineage_is_durable_and_replays_identically(attacked):
    ctx = attacked
    service, bid = ctx.service, ctx.board_id
    service.revise(bid, THRASYMACHUS, claimant_display="Thrasymachus",
                   in_response_to=ctx.ce1)
    service.revise(bid, "Justice is teaching what is good.",
                   claimant_display="Cephalus")
    state = service.state(bid)
    assert [state.nodes[nid].version for nid in ("n1", "n2", "n3")] == [1, 2, 3]
    assert state.active_node_id == "n3"
    assert state.nodes["n1"].text == S0
    assert fold_events(service.journals.read_all(bid)) == state
    assert service.journals.load_state(bid) == state
    mapping = service.provenance_map(bid)
    assert set(mapping) == {"n1", "n2", "n3"}
    assert mapping["n1"]["source"] == "dictionary-chain"
    assert mapping["n2"]["source"] is None
    assert mapping["n3"]["gloss"] is None
    assert [(e["seq"], e["type"]) for e in service.read_events(bid)] == [
        (1, CLAIM_RECORDED), (2, CLAIM_RECORDED), (3, CLAIM_REVISED),
        (4, CLAIM_RECORDED), (5, CLAIM_REVISED)]


def test_restart_from_disk_keeps_state_and_costs_zero_calls(attacked):
    ctx = attacked
    service, bid = ctx.service, ctx.board_id
    service.revise(bid, THRASYMACHUS, claimant_display="Thrasymachus")
    state = service.state(bid)
    chain = justice_chain()                 # a fresh chain with an empty cache
    rebuilt = make_service(service.root, chain=chain)
    assert rebuilt.state(bid) == state
    assert rebuilt.canonicals(bid) == service.canonicals(bid)
    assert rebuilt.provenance_map(bid) == service.provenance_map(bid)
    assert rebuilt.view(bid) == service.view(bid)
    assert len(chain.transport.calls) == 0, \
        "a reopened service renders from the disk cache with no pulls"


def test_journal_grows_only_with_machine_events(attacked):
    ctx = attacked
    service, bid = ctx.service, ctx.board_id
    before = [e["type"] for e in service.journals.read_all(bid)]
    service.revise(bid, THRASYMACHUS, claimant_display="Thrasymachus")
    added = Counter(e["type"] for e in service.journals.read_all(bid)) \
        - Counter(before)
    # the machine's own revision footprint: new node + one freeze per open Q
    assert added["node_registered"] == 1
    assert added["q_frozen"] == 2
    # the server writes no verdict events at all, into either log
    assert "claim_recorded" not in added and "ballot_cast" not in added
    assert len(service.meta.read_events(bid)) == 3
