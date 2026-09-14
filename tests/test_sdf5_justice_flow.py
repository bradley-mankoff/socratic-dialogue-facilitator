"""The Justice fixture walked end to end (stories 1–5, 11, 46 in one line).

Open a board on Justice → the canonicals arrive → Cephalus claims one → the
objections are answered by a *new* version node, and Thrasymachus' counter-
claim supersedes it with the live objections recorded as the tray SDF-7 will
pick up. Votes are cast through ``service.machine(...)`` on purpose: SDF-6
owns the scrutiny API, and this slice's job is to leave it reachable.
"""

from __future__ import annotations

import json

import pytest

from board.machine import fold_events
from server.model import CLAIM_RECORDED, CLAIM_REVISED
from tests.sdf5_stubs import (
    S0,
    THRASYMACHUS,
    empty_chain,
    justice_chain,
    make_service,
)


def test_justice_board_end_to_end(tmp_path):
    chain = justice_chain()
    service = make_service(tmp_path / "store", chain=chain)
    stub = chain.transport

    # 1. open the board: X, label, mode, canonical definitions
    opened = service.open_board("Justice (Republic Book I)", "socrates-room",
                                mode="participates", medium="async")
    bid = opened.board_id
    assert opened.created is True
    assert opened.record.x_title == "Justice (Republic Book I)"
    assert [s["sense_id"] for s in opened.view["canonicals"]["senses"]][:2] \
        == ["s0", "s1"]
    assert len(stub.calls) == 2

    # 2. Cephalus claims a canonical: it becomes the active definition (AC2)
    machine = service.machine(bid)
    cephalus = machine.enroll_handle("Cephalus")
    polemarchus = machine.enroll_handle("Polemarchus")
    thrasymachus = machine.enroll_handle("Thrasymachus")
    first = service.claim_canonical(bid, "s0", claimant_display="Cephalus")
    assert (first.node_id, first.version, first.is_active) == ("n1", 1, True)
    assert first.text == S0
    assert service.state(bid).active_node_id == "n1"

    # 3. two objections, voted in public (SDF-6 owns this API, not us)
    ce1, q1 = machine.open_refutation_q("n1", "3a", opened_by=thrasymachus)
    ce2, q2 = machine.open_refutation_q("n1", "3b", opened_by=thrasymachus)
    machine.cast(q1, cephalus, "explicit", "stands")
    machine.cast(q1, polemarchus, "explicit", "stands")
    machine.cast(q1, thrasymachus, "explicit", "rebutted")
    machine.cast(q2, cephalus, "explicit", "stands")
    machine.cast(q2, polemarchus, "explicit", "rebutted")
    machine.cast(q2, thrasymachus, "explicit", "rebutted")
    assert machine.node_status("n1") == "refuted"

    # 4. Thrasymachus answers ce1 with a new claim: a NEW node (AC3)
    second = service.revise(bid, THRASYMACHUS,
                            claimant_display="Thrasymachus",
                            in_response_to=ce1)
    state = service.state(bid)
    assert (second.node_id, second.version, second.is_active) == ("n2", 2, True)
    assert state.active_node_id == "n2"
    assert state.nodes["n1"].text == S0            # history not rewritten
    assert state.nodes["n1"].is_active is False
    assert sorted(second.frozen_q_ids) == sorted([q1, q2])

    # 5. the tray SDF-7 consumes: standing objections carried, losers recorded
    tray = second.revision_event["payload"]
    assert tray["tray"] == "carried_unvoted"
    assert [(row["ce_id"], row["carried"], row["outcome"])
            for row in tray["unresolved_ces"]] == [(ce1, True, "stands"),
                                                   (ce2, False, None)]
    assert [row["ce_id"] for row in tray["unresolved_ces"] if row["carried"]] \
        == [ce1]
    assert tray["prev_node_refuted"] is True
    assert tray["in_response_to"] == ce1

    # 6. provenance follows the claim, and the view is SDF-10-ready
    assert service.provenance(bid, "n1")["source"] == "dictionary-chain"
    assert service.provenance(bid, "n2")["source"] is None
    view = service.view(bid)
    assert json.loads(json.dumps(view)) == view
    assert view["cache"]["shared"] is False, "one board on this X so far"
    assert [n["version"] for n in view["nodes"]] == [1, 2]
    assert view["nodes"][1]["text"] == THRASYMACHUS
    assert view["nodes"][1]["provenance"]["claimed_by"] == thrasymachus
    assert view["canonicals"]["state"] == "ok"
    assert len(stub.calls) == 2, "the whole dialogue cost one canonical pull"

    # 7. a second room on the same X: new label, shared cache, clean slate
    other = service.open_board("Justice (Republic Book I)", "thrasy-room",
                              mode="facilitates")
    assert other.board_id != bid
    assert service.canonicals(other.board_id) == service.canonicals(bid)
    assert service.state(other.board_id).nodes == {}
    assert len(stub.calls) == 2
    assert service.view(bid)["cache"]["shared"] is True, \
        "the flag follows the X, not the board"

    # 8. ops log is append-only and replay rebuilds the identical board
    assert [(e["seq"], e["type"]) for e in service.read_events(bid)] == [
        (1, CLAIM_RECORDED), (2, CLAIM_RECORDED), (3, CLAIM_REVISED)]
    assert fold_events(service.journals.read_all(bid)) == state

    # 9. reopen from disk with a chain that would fail if it pulled anything
    rebuilt = make_service(tmp_path / "store", chain=empty_chain())
    assert rebuilt.state(bid) == state
    assert rebuilt.view(bid) == service.view(bid), \
        "a reopened service agrees with the live one, byte for byte"
    assert [r.label for r in rebuilt.list_boards("Justice (Republic Book I)")] \
        == ["socrates-room", "thrasy-room"]
    assert rebuilt.provenance(bid, "n1")["gloss"] == S0
    # a third claim is a revision too, never an edit of n2
    third = rebuilt.revise(bid, "Justice is teaching what is good.",
                           claimant_display="Cephalus")
    assert (third.node_id, third.version) == ("n3", 3)
    assert rebuilt.state(bid).nodes["n2"].text == THRASYMACHUS
    assert len(rebuilt.meta.read_events(bid)) == 5


def test_board_opens_and_claims_with_an_empty_dictionary(tmp_path):
    """Nothing found is a legitimate state, not a failure: author instead."""
    service = make_service(tmp_path / "store", chain=empty_chain())
    opened = service.open_board("Justice")
    assert opened.view["canonicals"]["state"] == "empty"
    assert opened.view["canonicals"]["senses"] == []
    from server.errors import EmptyCanonicals
    with pytest.raises(EmptyCanonicals):
        service.claim_canonical(opened.board_id,
                               claimant_display="Cephalus")
    result = service.claim_original(opened.board_id, THRASYMACHUS,
                                   claimant_display="Cephalus")
    assert result.is_active is True
    revised = service.revise(opened.board_id, "Justice is reciprocity.",
                            claimant_display="Polemarchus")
    assert revised.version == 2
    assert revised.revision_event["payload"]["unresolved_ces"] == []
    assert service.view(opened.board_id)["canonicals"]["state"] == "empty"
