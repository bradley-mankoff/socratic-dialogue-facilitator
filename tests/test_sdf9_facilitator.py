"""SDF-9 AC3 — in Facilitates mode the facilitator holds no seat, no ballot.

Guards are Facilitates-scoped: the same calls succeed in Participates mode
(SDF-2 symmetry). The ballot half reuses ``FacilitatorCannotVote`` and the
census exclusion; the seat half is new here.
"""

import pytest

from board.machine import (
    FacilitatorCannotVote,
    FacilitatorHoldsNoSeat,
    UnknownNode,
    VerdictError,
)
from tests.sdf9_stubs import CLAIM, open_justice, settle_side

VOTERS = ("Cephalus", "Polemarchus", "Thrasymachus")


def test_facilitator_cannot_take_seat(sdf5_svc):
    env = open_justice(sdf5_svc, mode="facilitates", facilitator=True)
    m, h, f = env.machine, env.h, env.f
    with pytest.raises(FacilitatorHoldsNoSeat):
        m.set_socrates(f)
    with pytest.raises(FacilitatorHoldsNoSeat):
        m.open_governance_q("socrates_swap", subject=f,
                            opened_by=h["Cephalus"])
    assert m.socrates_seat() is None


def test_facilitator_cannot_take_or_receive_defense(sdf5_svc):
    env = open_justice(sdf5_svc, mode="facilitates", facilitator=True)
    m, h, f = env.machine, env.h, env.f
    with pytest.raises(FacilitatorHoldsNoSeat):
        m.register_node("direct", "a claim defended by the facilitator",
                        defender=f)
    env.service.claim_original(env.board_id, CLAIM,
                               claimant_display="Cephalus")
    with pytest.raises(FacilitatorHoldsNoSeat):
        m.offer_defense(f, by=h["Cephalus"])

    # G4: an offer made while participates survives the mode flip and is
    # still refused at accept time
    env2 = open_justice(sdf5_svc, mode="participates", facilitator=True)
    m2, h2, f2 = env2.machine, env2.h, env2.f
    env2.service.claim_original(env2.board_id, CLAIM,
                                claimant_display="Cephalus")
    m2.offer_defense(f2, by=h2["Cephalus"])
    mq = m2.open_governance_q("mode_switch", subject="facilitates",
                              opened_by=h2["Cephalus"])
    assert settle_side(m2, mq, [h2[v] for v in VOTERS], "for")[1] == "for"
    assert m2.state.mode == "facilitates"
    with pytest.raises(FacilitatorHoldsNoSeat):
        m2.accept_defense(f2)
    assert m2.defender() == h2["Cephalus"]


def test_facilitator_no_ballot_on_seat_questions(sdf5_svc):
    env = open_justice(sdf5_svc, mode="facilitates", facilitator=True)
    m, h, f = env.machine, env.h, env.f
    m.set_socrates(h["Cephalus"])
    q = m.open_governance_q("socrates_swap", subject=h["Socrates"],
                            opened_by=h["Cephalus"])
    with pytest.raises(FacilitatorCannotVote):
        m.cast(q, f, "explicit", "for")
    assert f not in m.census(q)
    assert settle_side(m, q, [h[v] for v in VOTERS], "for") == \
        ("settled", "for")
    assert m.socrates_seat() == h["Socrates"]


def test_facilitator_may_hold_seat_in_participates(sdf5_svc):
    env = open_justice(sdf5_svc, mode="participates", facilitator=True)
    m, h, f = env.machine, env.h, env.f
    m.set_socrates(f)
    assert m.socrates_seat() == f
    m.register_node("direct", "defended by the facilitator", defender=f)
    assert m.defender() == f

    # a named swap to the facilitator also settles in participates
    m.set_socrates(h["Cephalus"])
    q = m.open_governance_q("socrates_swap", subject=f,
                            opened_by=h["Cephalus"])
    assert settle_side(m, q, [h[v] for v in VOTERS], "for") == \
        ("settled", "for")
    assert m.socrates_seat() == f


def test_mode_switch_to_facilitates_refused_while_facilitator_holds_role(
        sdf5_svc):
    env = open_justice(sdf5_svc, mode="participates", facilitator=True)
    m, h, f = env.machine, env.h, env.f
    m.set_socrates(f)
    with pytest.raises(FacilitatorHoldsNoSeat):
        m.open_governance_q("mode_switch", subject="facilitates",
                            opened_by=h["Cephalus"])
    assert m.state.mode == "participates"
    assert not [e for e in m.events
                if e["type"] == "mode_switch_applied"]

    # rotate the seat out via a named swap; then the switch opens
    q = m.open_governance_q("socrates_swap", subject=h["Cephalus"],
                            opened_by=h["Polemarchus"])
    settle_side(m, q, [h[v] for v in VOTERS], "for")
    assert m.socrates_seat() == h["Cephalus"]
    mq = m.open_governance_q("mode_switch", subject="facilitates",
                             opened_by=h["Cephalus"])
    assert m.q_status(mq)[0] == "open"

    # the defense variant refuses too
    env2 = open_justice(sdf5_svc, mode="participates", facilitator=True)
    m2, h2, f2 = env2.machine, env2.h, env2.f
    m2.register_node("defended", "a claim", defender=f2)
    with pytest.raises(FacilitatorHoldsNoSeat):
        m2.open_governance_q("mode_switch", subject="facilitates",
                             opened_by=h2["Cephalus"])


def test_swap_to_facilitator_skips_silently_after_mode_flip(sdf5_svc):
    """G8 backstop: a swap Q opened while participates may settle after the
    flip; the arm skips rather than raising out of ``cast``."""
    env = open_justice(sdf5_svc, mode="participates", facilitator=True)
    m, h, f = env.machine, env.h, env.f
    m.set_socrates(h["Cephalus"])
    q = m.open_governance_q("socrates_swap", subject=f,
                            opened_by=h["Cephalus"])
    mq = m.open_governance_q("mode_switch", subject="facilitates",
                             opened_by=h["Cephalus"])
    assert settle_side(m, mq, [h[v] for v in VOTERS], "for")[1] == "for"
    assert m.state.mode == "facilitates"
    assert settle_side(m, q, [h[v] for v in VOTERS], "for") == \
        ("settled", "for")
    assert m.socrates_seat() == h["Cephalus"]     # skipped, not applied


def test_active_switch_guards(sdf5_svc):
    env = open_justice(sdf5_svc)
    m, h, svc = env.machine, env.h, env.service
    svc.claim_original(env.board_id, CLAIM, claimant_display="Cephalus")
    with pytest.raises(VerdictError):              # already active
        m.open_governance_q("active_claim_switch", subject="n1",
                            opened_by=h["Cephalus"])
    with pytest.raises(UnknownNode):               # unknown target
        m.open_governance_q("active_claim_switch", subject="ghost",
                            opened_by=h["Cephalus"])


def test_active_switch_to_facilitator_defended_node_refused(sdf5_svc):
    """G6: an inactive node defended by the facilitator cannot be made
    active in Facilitates mode (raw path around cede's G3/G4)."""
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


def test_tiebreak_unchanged(sdf5_svc):
    env = open_justice(sdf5_svc, mode="facilitates", facilitator=True,
                       humans=("Cephalus", "Polemarchus", "Thrasymachus"))
    m, h, f = env.machine, env.h, env.f
    n = m.register_node("n1", CLAIM)
    ce, q = m.open_refutation_q(n, "3a", opened_by=h["Cephalus"])
    m.cast(q, h["Cephalus"], "explicit", "stands")
    m.cast(q, h["Polemarchus"], "explicit", "rebutted")
    tb = m.open_governance_q("tiebreak", subject=ce,
                             opened_by=h["Cephalus"])
    settle_side(m, tb, [h["Cephalus"], h["Polemarchus"]], "for")
    ballot = m.tiebreak_ballot(ce, "the example misapplies the term")
    assert m.state.ces[ce].tiebreak_ballot_id == ballot
    assert f not in m.census(q)
