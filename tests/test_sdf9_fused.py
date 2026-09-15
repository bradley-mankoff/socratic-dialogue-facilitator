"""Fused SDF-9 synthesis test — proves the fuse is not a pick.

Covers the union no single panel covers alone:
- panel a: G6 active-switch defender guard + original-event idempotent offer.
- panel b: service payload shape {board_id, from, to, node_id} + sync,
  nameless ValueError shape (via InvalidGovernanceSubject hybrid).
- panel c: roles_view/seats_view pure read + decline/withdraw lifecycle.

AC mapping: AC1 seat-owned (4c4de835), AC2 cede-without-accept (0a544a9b),
AC3 facilitator holds no seat/ballot (9bd0449f).
"""

import json

import pytest

from board.machine import (
    FacilitatorHoldsNoSeat,
    InvalidGovernanceSubject,
    NoPendingCede,
    NotCedeTarget,
    NotDefender,
    UnknownHandle,
)
from tests.sdf9_stubs import CLAIM, open_justice, reload_state, settle_side

VOTERS = ("Cephalus", "Polemarchus", "Thrasymachus")


def _claimed(svc):
    env = open_justice(svc)
    svc.claim_original(env.board_id, CLAIM, claimant_display="Thrasymachus")
    return env


def test_fused_service_payload_shape_and_idempotent_event(sdf5_svc):
    # Panel a machine contract: identical re-offer returns original event.
    env = _claimed(sdf5_svc)
    m, h = env.machine, env.h
    first = m.offer_defense(h["Polemarchus"], by=h["Thrasymachus"])
    again = m.offer_defense(h["Polemarchus"], by=h["Thrasymachus"])
    assert again == first
    assert first["type"] == "defense_cede_offered"
    # Panel b service contract: payload keys plus board_id.
    offered = env.service.offer_defense(
        env.board_id, h["Socrates"], by=h["Thrasymachus"])
    # re-target supersedes (both panels agree)
    assert offered["to"] == h["Socrates"]
    assert offered["board_id"] == env.board_id
    assert m.defender() == h["Thrasymachus"]  # AC2: offer moves nothing
    accepted = env.service.accept_defense(env.board_id, by=h["Socrates"])
    assert accepted["from"] == h["Thrasymachus"]
    assert accepted["board_id"] == env.board_id
    assert m.defender() == h["Socrates"]


def test_fused_nameless_hybrid_satisfies_both_panels(sdf5_svc):
    # Panel b expects ValueError, panel a expects UnknownHandle/UnknownNode.
    # The fused hybrid is all three at once.
    env = open_justice(sdf5_svc)
    m = env.machine
    with pytest.raises(ValueError):
        m.open_governance_q("socrates_swap", subject=None)
    with pytest.raises(UnknownHandle):
        m.open_governance_q("socrates_swap", subject=None)
    with pytest.raises(InvalidGovernanceSubject):
        m.open_governance_q("socrates_swap", subject="")
    with pytest.raises(ValueError):
        m.open_governance_q("active_claim_switch", subject="")
    # non-blank unknown still raises the plain errors, no auto-enroll
    before = len(m.state.handles)
    with pytest.raises(UnknownHandle):
        m.open_governance_q("socrates_swap", subject="ghost",
                            opened_by=env.h["Cephalus"])
    assert len(m.state.handles) == before


def test_fused_g6_active_switch_to_facilitator_defended_node_refused(sdf5_svc):
    # Panel a's G6: an inactive node defended by the facilitator cannot be
    # made active in Facilitates mode (raw path around cede's G3/G4).
    # Panel b dropped this guard; the fuse keeps it (mirrors panel a's
    # G6 test: three nodes in participates, flip to facilitates, then the
    # switch onto the facilitator-defended inactive node refuses).
    env = open_justice(sdf5_svc, mode="participates", facilitator=True)
    m, h, f = env.machine, env.h, env.f
    m.register_node("n1", "first claim", defender=h["Cephalus"])
    m.register_node("n2", "facilitator-defended claim", defender=f)
    m.register_node("n3", "third claim", defender=h["Cephalus"])
    assert m.defender() == h["Cephalus"]
    mq = m.open_governance_q("mode_switch", subject="facilitates",
                             opened_by=h["Cephalus"])
    assert settle_side(m, mq, [h[v] for v in VOTERS], "for")[1] == "for"
    with pytest.raises(FacilitatorHoldsNoSeat):
        m.open_governance_q("active_claim_switch", subject="n2",
                            opened_by=h["Cephalus"])
    assert m.state.active_node_id == "n3"


def test_fused_decline_withdraw_clear_without_moving(sdf5_svc):
    # Panel c lifecycle, re-vocabularized onto the a/b event family:
    # decline/withdraw are journaled closes that leave defense unchanged.
    env = _claimed(sdf5_svc)
    m, h = env.machine, env.h
    m.offer_defense(h["Polemarchus"], by=h["Thrasymachus"])
    m.decline_defense(h["Polemarchus"])
    assert m.defender() == h["Thrasymachus"]
    assert m.state.pending_defense_offer is None
    assert m.events[-1]["type"] == "defense_cede_declined"
    assert reload_state(sdf5_svc, env.board_id) == m.state

    m.offer_defense(h["Polemarchus"], by=h["Thrasymachus"])
    m.withdraw_defense(h["Thrasymachus"])
    assert m.defender() == h["Thrasymachus"]
    assert m.state.pending_defense_offer is None
    assert m.events[-1]["type"] == "defense_cede_withdrawn"

    # guards reuse the existing vocabulary
    m.offer_defense(h["Polemarchus"], by=h["Thrasymachus"])
    with pytest.raises(NotCedeTarget):
        m.decline_defense(h["Cephalus"])
    with pytest.raises(NotDefender):
        m.withdraw_defense(h["Cephalus"])
    m.decline_defense(h["Polemarchus"])
    assert m.state.pending_defense_offer is None
    with pytest.raises(NoPendingCede):
        m.decline_defense(h["Polemarchus"])
    with pytest.raises(NoPendingCede):
        m.withdraw_defense(h["Thrasymachus"])
    m.offer_defense(h["Cephalus"], by=h["Thrasymachus"])
    out = env.service.withdraw_defense(env.board_id, by=h["Thrasymachus"])
    assert out["to"] == h["Cephalus"]
    assert m.defender() == h["Thrasymachus"]


def test_fused_roles_view_matches_machine(sdf5_svc):
    # Panel c UI intent on the a/b schema: the view cannot disagree.
    from server.views import roles_view
    from board.roles import seats_view

    env = _claimed(sdf5_svc)
    m, h = env.machine, env.h
    m.set_socrates(h["Cephalus"])
    snap = seats_view(m.state)
    assert snap["socrates"] == h["Cephalus"]
    assert snap["defense"] == h["Thrasymachus"]
    assert snap["pending_cede"] is None
    assert roles_view(m.state) == snap
    m.offer_defense(h["Polemarchus"], by=h["Thrasymachus"])
    assert roles_view(m.state)["pending_cede"]["to"] == h["Polemarchus"]
    assert roles_view(m.state)["defense"] == h["Thrasymachus"]  # unchanged
    # board_view carries the roles block (panel c) and stays JSON-able
    view = env.service.view(env.board_id)
    assert view["roles"]["socrates"] == h["Cephalus"]
    assert json.loads(json.dumps(view)) == view
