"""Defender rule — the defender is the active claimant at all times."""

import pytest

from board.machine import NotDefender
from tests.sdf9_stubs import CLAIM, REVISION, open_justice


def test_defender_follows_registration_claim_and_revision(sdf5_svc):
    env = open_justice(sdf5_svc)
    m, h, svc = env.machine, env.h, env.service
    svc.claim_original(env.board_id, CLAIM, claimant_display="Cephalus")
    assert m.defender() == h["Cephalus"]
    svc.revise(env.board_id, REVISION, claimant_display="Thrasymachus")
    assert m.defender() == h["Thrasymachus"]
    # the field lives per node: the superseded claim keeps its own defender
    assert m.state.nodes["n1"].defender == h["Cephalus"]
    assert m.state.nodes["n2"].defender == h["Thrasymachus"]


def test_defender_equals_active_claimant_always(sdf5_svc):
    env = open_justice(sdf5_svc)
    m, h, svc = env.machine, env.h, env.service
    svc.claim_original(env.board_id, CLAIM, claimant_display="Cephalus")
    assert m.defender() == m.state.nodes[m.state.active_node_id].defender
    assert m.require_defender(h["Cephalus"]) == h["Cephalus"]
    with pytest.raises(NotDefender):
        m.require_defender(h["Polemarchus"])

    svc.revise(env.board_id, REVISION, claimant_display="Polemarchus")
    assert m.defender() == m.state.nodes[m.state.active_node_id].defender
    assert m.require_defender(h["Polemarchus"]) == h["Polemarchus"]


def test_machine_direct_register_without_defender_has_no_defense(sdf5_svc):
    env = open_justice(sdf5_svc)
    m = env.machine
    m.register_node("n1", CLAIM)          # legacy call: no claimant
    assert m.defender() is None
    with pytest.raises(NotDefender):
        m.require_defender(env.h["Cephalus"])


def test_defender_untouched_by_non_claim_writes(sdf5_svc):
    env = open_justice(sdf5_svc)
    m, h, svc = env.machine, env.h, env.service
    svc.claim_original(env.board_id, CLAIM, claimant_display="Cephalus")
    _ce, q = m.open_refutation_q(m.state.active_node_id, "3a",
                                 opened_by=h["Polemarchus"])
    m.cast(q, h["Polemarchus"], "explicit", "stands")
    m.toggle_medium("live")
    assert m.defender() == h["Cephalus"]
