"""SDF-9 — Justice arc end to end: seat, defense, facilitator, reload.

One board exercises all three acceptance criteria in order, then proves the
closed board refuses every SDF-9 mutation.
"""

import pytest

from board.machine import BoardClosed, FacilitatorCannotVote
from tests.sdf9_stubs import CLAIM, open_justice, reload_state, settle_side

VOTERS = ("Cephalus", "Polemarchus", "Thrasymachus")


def test_justice_roles_end_to_end(sdf5_svc, sdf5_store):
    env = open_justice(sdf5_svc, mode="facilitates", facilitator=True)
    m, h, f, svc = env.machine, env.h, env.f, env.service

    # AC1 — seat has an owner from first assignment; named swap rotates it
    m.set_socrates(h["Cephalus"])
    assert m.socrates_seat() == h["Cephalus"]
    svc.claim_original(env.board_id, CLAIM, claimant_display="Thrasymachus")
    assert m.defender() == h["Thrasymachus"]

    q = m.open_governance_q("socrates_swap", subject=h["Socrates"],
                            opened_by=h["Cephalus"])
    with pytest.raises(FacilitatorCannotVote):     # AC3 — no ballot
        m.cast(q, f, "explicit", "for")
    assert f not in m.census(q)
    assert settle_side(m, q, [h[v] for v in VOTERS], "for") == \
        ("settled", "for")
    assert m.socrates_seat() == h["Socrates"]

    # AC2 — offer alone changes nothing; accept moves the defense
    svc.offer_defense(env.board_id, h["Polemarchus"],
                      by=h["Thrasymachus"])
    assert m.defender() == h["Thrasymachus"]
    svc.accept_defense(env.board_id, by="Polemarchus")   # display resolves
    assert m.defender() == h["Polemarchus"]
    assert m.socrates_seat() == h["Socrates"]

    assert reload_state(sdf5_svc, env.board_id) == m.state

    # closed board: every SDF-9 mutation refuses
    qc = m.open_governance_q("close", opened_by=h["Cephalus"])
    for voter in VOTERS:
        m.cast(qc, h[voter], "explicit", "for")
    assert m.is_closed()
    with pytest.raises(BoardClosed):
        svc.offer_defense(env.board_id, h["Socrates"],
                          by=h["Polemarchus"])
    with pytest.raises(BoardClosed):
        svc.accept_defense(env.board_id, by=h["Socrates"])
    with pytest.raises(BoardClosed):
        m.open_governance_q("socrates_swap", subject=h["Socrates"],
                            opened_by=h["Socrates"])
