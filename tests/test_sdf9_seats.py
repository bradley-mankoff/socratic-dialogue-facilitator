"""SDF-9 AC1 — the Socrates seat has an owner at all times.

Covers stories 26/27: named-swap rotation (never a vacating Q), no vacate
verb, and leavers keeping the seat until a settled swap reassigns it.
"""

import pytest

from board.machine import SeatNeverVacant, UnknownHandle
from tests.sdf9_stubs import CLAIM, open_justice, reload_state, settle_side

VOTERS = ("Cephalus", "Polemarchus", "Thrasymachus")


def _settle_swap(env, target, by, side="for", voters=VOTERS):
    m, h = env.machine, env.h
    q = m.open_governance_q("socrates_swap", subject=target, opened_by=by)
    return q, settle_side(m, q, [h[v] for v in voters], side)


def test_named_swap_settles_for_moves_the_seat(sdf5_svc, sdf5_store):
    env = open_justice(sdf5_svc)
    m, h = env.machine, env.h
    m.set_socrates(h["Cephalus"])
    q, status = _settle_swap(env, h["Socrates"], h["Cephalus"])
    assert status == ("settled", "for")
    assert m.socrates_seat() == h["Socrates"]
    # journal ordering: the settled mandate is followed by the seat write
    assert [e["type"] for e in m.events][-2:] == ["q_settled", "socrates_set"]
    assert reload_state(sdf5_svc, env.board_id) == m.state


def test_set_socrates_none_refused(sdf5_svc):
    env = open_justice(sdf5_svc)
    m, h = env.machine, env.h
    assert m.socrates_seat() is None
    with pytest.raises(SeatNeverVacant):
        m.set_socrates(None)
    m.set_socrates(h["Cephalus"])
    with pytest.raises(SeatNeverVacant):
        m.set_socrates(None)
    assert m.socrates_seat() == h["Cephalus"]


def test_nameless_swap_refused_at_open(sdf5_svc):
    env = open_justice(sdf5_svc)
    with pytest.raises(UnknownHandle):
        env.machine.open_governance_q("socrates_swap", subject=None,
                                      opened_by=env.h["Cephalus"])
    assert not [e for e in env.machine.events if e["type"] == "q_opened"]


def test_swap_to_unknown_refused_no_auto_enroll(sdf5_svc):
    env = open_justice(sdf5_svc)
    m = env.machine
    before = len(m.state.handles)
    with pytest.raises(UnknownHandle):
        m.open_governance_q("socrates_swap", subject="ghost",
                            opened_by=env.h["Cephalus"])
    assert len(m.state.handles) == before


def test_settled_against_leaves_seat(sdf5_svc):
    env = open_justice(sdf5_svc)
    m, h = env.machine, env.h
    m.set_socrates(h["Cephalus"])
    _, status = _settle_swap(env, h["Socrates"], h["Cephalus"],
                             side="against")
    assert status == ("settled", "against")
    assert m.socrates_seat() == h["Cephalus"]
    # an against mandate has no consequence event after q_settled
    assert [e["type"] for e in m.events][-1] == "q_settled"
    # a rejected swap frees the slot: the room may propose again
    q2 = m.open_governance_q("socrates_swap", subject=h["Socrates"],
                             opened_by=h["Cephalus"])
    assert m.q_status(q2)[0] == "open"


def test_leaver_keeps_seat_until_reassigned(sdf5_svc):
    env = open_justice(sdf5_svc)
    m, h, svc = env.machine, env.h, env.service
    svc.claim_original(env.board_id, CLAIM, claimant_display="Thrasymachus")
    m.set_socrates(h["Cephalus"])

    # churn: a late joiner, a counterexample vote, medium toggle, an
    # unaccepted cede offer, a rejected swap, and a mode round-trip
    late = m.enroll_handle("Glaucon")
    ce, q = m.open_refutation_q(m.state.active_node_id, "3a", opened_by=late)
    m.cast(q, late, "explicit", "stands")
    m.toggle_medium("live")
    m.offer_defense(h["Polemarchus"], by=h["Thrasymachus"])
    _settle_swap(env, h["Socrates"], h["Cephalus"], side="against")

    mq = m.open_governance_q("mode_switch", subject="facilitates",
                             opened_by=h["Cephalus"])
    settle_side(m, mq, [h[v] for v in VOTERS], "for")
    assert m.state.mode == "facilitates"
    mq2 = m.open_governance_q("mode_switch", subject="participates",
                              opened_by=h["Cephalus"])
    settle_side(m, mq2, [h[v] for v in VOTERS], "for")
    assert m.state.mode == "participates"

    # no leave/unenroll op exists; none of the churn vacated the seat
    assert m.socrates_seat() == h["Cephalus"]


def test_later_rejected_swap_does_not_revoke(sdf5_svc):
    env = open_justice(sdf5_svc)
    m, h = env.machine, env.h
    m.set_socrates(h["Cephalus"])
    _settle_swap(env, h["Socrates"], h["Cephalus"])
    assert m.socrates_seat() == h["Socrates"]
    _settle_swap(env, h["Polemarchus"], h["Socrates"], side="against")
    assert m.socrates_seat() == h["Socrates"]
