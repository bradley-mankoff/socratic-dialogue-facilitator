"""SDF-9 AC2 — a cede is offer + accept, both journaled, no vote.

An offer alone changes nothing about who defends (defense unchanged, no
question, no ballot); accept moves the defense and clears the offer; stale
offers refuse instead of moving the wrong claim's defense.
"""

import pytest

from board.machine import (
    NoPendingCede,
    NotCedeTarget,
    NotDefender,
    StaleCede,
    UnknownHandle,
)
from tests.sdf9_stubs import CLAIM, open_justice, reload_state, settle_side

VOTERS = ("Cephalus", "Polemarchus", "Thrasymachus")


def _claimed(svc, *, mode="participates", facilitator=False):
    env = open_justice(svc, mode=mode, facilitator=facilitator)
    svc.claim_original(env.board_id, CLAIM,
                       claimant_display="Thrasymachus")
    return env


def test_offer_changes_nothing(sdf5_svc):
    env = _claimed(sdf5_svc)
    m, h = env.machine, env.h
    assert m.defender() == h["Thrasymachus"]
    before_q, before_b = len(m.state.questions), len(m.state.ballots)

    m.offer_defense(h["Polemarchus"], by=h["Thrasymachus"])

    assert m.defender() == h["Thrasymachus"]
    assert m.state.pending_defense_offer == {
        "from": h["Thrasymachus"], "to": h["Polemarchus"],
        "node_id": m.state.active_node_id,
    }
    assert [e["type"] for e in m.events].count("defense_cede_offered") == 1
    # no ballot, no question: cede never touches census or tallies
    assert len(m.state.questions) == before_q
    assert len(m.state.ballots) == before_b


def test_accept_moves_defense_clears_pending(sdf5_svc):
    env = _claimed(sdf5_svc)
    m, h = env.machine, env.h
    m.offer_defense(h["Polemarchus"], by=h["Thrasymachus"])
    m.accept_defense(h["Polemarchus"])
    assert m.defender() == h["Polemarchus"]
    assert m.state.nodes[m.state.active_node_id].defender == h["Polemarchus"]
    assert m.state.pending_defense_offer is None
    assert [e["type"] for e in m.events].count("defense_cede_accepted") == 1


def test_accept_without_offer_raises(sdf5_svc):
    env = _claimed(sdf5_svc)
    with pytest.raises(NoPendingCede):
        env.machine.accept_defense(env.h["Polemarchus"])


def test_accept_by_wrong_handle_raises(sdf5_svc):
    env = _claimed(sdf5_svc)
    m, h = env.machine, env.h
    m.offer_defense(h["Polemarchus"], by=h["Thrasymachus"])
    with pytest.raises(NotCedeTarget):
        m.accept_defense(h["Cephalus"])
    assert m.defender() == h["Thrasymachus"]


def test_offer_guards(sdf5_svc):
    env = _claimed(sdf5_svc)
    m, h = env.machine, env.h

    count = len(m.state.handles)
    with pytest.raises(UnknownHandle):
        m.offer_defense("ghost", by=h["Thrasymachus"])
    assert len(m.state.handles) == count          # no auto-enroll

    with pytest.raises(ValueError):
        m.offer_defense(h["Thrasymachus"], by=h["Thrasymachus"])

    with pytest.raises(NotDefender):
        m.offer_defense(h["Polemarchus"], by=h["Cephalus"])

    first = m.offer_defense(h["Polemarchus"], by=h["Thrasymachus"])
    again = m.offer_defense(h["Polemarchus"], by=h["Thrasymachus"])
    assert again == first                         # idempotent re-offer
    assert [e["type"] for e in m.events].count("defense_cede_offered") == 1

    m.offer_defense(h["Cephalus"], by=h["Thrasymachus"])
    assert m.state.pending_defense_offer["to"] == h["Cephalus"]
    assert [e["type"] for e in m.events].count("defense_cede_offered") == 2


def test_stale_cede_after_claim_switch(sdf5_svc):
    env = open_justice(sdf5_svc)
    m, h, svc = env.machine, env.h, env.service
    svc.claim_original(env.board_id, CLAIM, claimant_display="Cephalus")
    svc.revise(env.board_id, CLAIM + " (revised)",
               claimant_display="Polemarchus")
    assert m.defender() == h["Polemarchus"]

    m.offer_defense(h["Thrasymachus"], by=h["Polemarchus"])
    q = m.open_governance_q("active_claim_switch", subject="n1",
                            opened_by=h["Cephalus"])
    assert settle_side(m, q, [h[v] for v in VOTERS], "for")[1] == "for"
    assert m.state.active_node_id == "n1"

    with pytest.raises(StaleCede):
        m.accept_defense(h["Thrasymachus"])
    assert m.state.pending_defense_offer is not None   # left for inspection
    assert m.defender() == h["Cephalus"]

    # a fresh offer on the now-active claim accepts cleanly
    m.offer_defense(h["Thrasymachus"], by=h["Cephalus"])
    m.accept_defense(h["Thrasymachus"])
    assert m.defender() == h["Thrasymachus"]


def test_replay_carries_offer_and_defense(sdf5_svc):
    env = _claimed(sdf5_svc)
    m, h = env.machine, env.h
    m.offer_defense(h["Polemarchus"], by=h["Thrasymachus"])

    reloaded = reload_state(sdf5_svc, env.board_id)
    assert reloaded == m.state
    assert reloaded.pending_defense_offer["to"] == h["Polemarchus"]
    assert reloaded.nodes[reloaded.active_node_id].defender == \
        h["Thrasymachus"]

    m.accept_defense(h["Polemarchus"])
    reloaded = reload_state(sdf5_svc, env.board_id)
    assert reloaded == m.state
    assert reloaded.pending_defense_offer is None
    assert reloaded.nodes[reloaded.active_node_id].defender == \
        h["Polemarchus"]
